# dk_results

## Contest Warning Schedules

`update_contests.py` runs every 10 minutes via cron, so warnings are evaluated in time
windows rather than at exact timestamps.

Configuration:
- `CONTEST_WARNING_SCHEDULE_FILE` (default `contest_warning_schedules.yaml`)
- `CONTEST_WARNING_MINUTES` fallback default (default `25`)

Schedule file format (keys are sport names; case-insensitive):

```yaml
default: [25]
NBA: [60, 30, 10]
```
