#!/usr/bin/env bash
# Jeden przebieg GitHub Actions pracuje ok. 5 h 20 min i sam powtarza zbieranie co ~11 min (w dzień roboczy)
# albo co ~50 min (noc, weekend). Dzięki temu łańcuch przekazuje pałeczkę tylko ~4 razy na dobę zamiast ~100,
# a każde przekazanie jest sprawdzane (patrz krok „Następca” w workflow).
set -u
END=$(( $(date +%s) + 5*3600 + 20*60 ))
git config user.name "zbieracz-bot"
git config user.email "zbieracz-bot@users.noreply.github.com"
while :; do
  T0=$(date +%s)
  git pull -q --rebase -X theirs || { git rebase --abort 2>/dev/null; git reset -q --hard origin/main; }
  python collector/collect.py || echo "collect: błąd (kontynuuję)"
  python collector/export.py || echo "export: błąd"
  python collector/digest.py || echo "digest: błąd"
  git add data config
  if ! git diff --cached --quiet; then
    git commit -q -m "Dane $(TZ=Europe/Warsaw date +'%F %H:%M')"
    for i in 1 2 3 4 5; do git pull -q --rebase -X theirs && git push -q && break; git rebase --abort 2>/dev/null; sleep $((5*i)); done
  fi
  H=$(TZ=Europe/Warsaw date +%-H); D=$(TZ=Europe/Warsaw date +%u)
  WAIT=3000
  if [ "$D" -le 5 ] && [ "$H" -ge 6 ]; then WAIT=660; fi
  if [ "$D" -ge 2 ] && [ "$D" -le 6 ] && [ "$H" -ge 4 ] && [ "$H" -lt 6 ]; then WAIT=660; fi
  NEXT=$(( T0 + WAIT ))
  if [ "$NEXT" -ge "$END" ]; then echo "koniec okna przebiegu"; break; fi
  NOW=$(date +%s); [ "$NEXT" -gt "$NOW" ] && sleep $(( NEXT - NOW ))
done
