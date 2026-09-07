#!/bin/bash
# Запускает workflow синхронизации в GitHub Actions.
#
# Планировщик самого GitHub у приватных репозиториев пропускает большую часть
# слотов: замерено 6 прогонов за 20 часов вместо 19. Этот скрипт вызывается
# launchd-агентом и дёргает workflow принудительно, поэтому интервал
# предсказуемый. Синхронизацию по-прежнему выполняет Actions — значит
# state.json остаётся с единственным писателем и гонок за него нет.

set -euo pipefail

GH="/Users/remurkov/.local/bin/gh"
REPO="okoloculture/Munis_bot"
WORKFLOW="sync.yml"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

if [ ! -x "$GH" ]; then
  log "ОШИБКА: gh не найден по пути $GH"
  exit 1
fi

# Если предыдущий прогон ещё идёт, второй не нужен: в workflow стоит
# concurrency, он всё равно встанет в очередь и просто сожжёт минуты.
running="$("$GH" run list --repo "$REPO" --workflow "$WORKFLOW" \
  --status in_progress --limit 1 --json databaseId --jq 'length' 2>/dev/null || echo 0)"
if [ "${running:-0}" != "0" ]; then
  log "пропуск: предыдущий прогон ещё выполняется"
  exit 0
fi

if "$GH" workflow run "$WORKFLOW" --repo "$REPO" >/dev/null 2>&1; then
  log "синхронизация запущена"
else
  log "ОШИБКА: не удалось запустить workflow"
  exit 1
fi
