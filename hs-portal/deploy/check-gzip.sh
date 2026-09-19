#!/bin/bash
# 압축이 실제로 적용됐는지 확인한다.
URL="${1:-https://udjschool.ggm.kr}"
echo "압축 적용 확인 — $URL"
echo "────────────────────────────────────────"
JS=$(curl -s "$URL" | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
for path in "/" "$JS"; do
  [ -z "$path" ] && continue
  RAW=$(curl -s -o /dev/null -w '%{size_download}' "$URL$path")
  GZ=$(curl -s -H "Accept-Encoding: gzip" -o /dev/null -w '%{size_download}' "$URL$path")
  ENC=$(curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null "$URL$path" | grep -i "content-encoding" | tr -d '\r')
  echo "$path"
  echo "  압축 없이 : $((RAW/1024)) KB"
  echo "  압축 요청 : $((GZ/1024)) KB   ${ENC:-(Content-Encoding 헤더 없음 → 압축 안 됨)}"
done
