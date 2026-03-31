# Sample Runbook

## Nginx reload failed
priority_score: 1.8
Check nginx syntax with `nginx -t` before reload. If the output reports an include file issue, verify `/etc/nginx/conf.d/` for recent changes.

## Disk usage above 90 percent
priority_score: 1.4
Review `/var/log` growth first. Rotate logs and clear stale archives before deleting active service data.

### Recovery sequence
If the root partition stays above 95 percent after rotation, move large archives to mounted backup storage and re-check service health.
