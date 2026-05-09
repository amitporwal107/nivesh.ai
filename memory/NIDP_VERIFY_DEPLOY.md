# NIDP — How to verify a GitHub push fired triggers and deployed cleanly

## After `git push origin nidp` (or "Save to GitHub" button)

### 1. Check active builds
```bash
gcloud builds list --region=asia-south1 \
  --filter='status=WORKING OR status=QUEUED' \
  --format='table(id,status,substitutions._SERVICE,createTime)'
```
Expect: one build per changed service.

### 2. Check most recent builds per service
```bash
gcloud builds list --region=asia-south1 --limit=15 \
  --format='table(id,status,substitutions._SERVICE,createTime,duration)'
```
Expect: SUCCESS for the affected services (amfi_nav_history, price_adjuster, delivery, fno_bhavcopy, and shared/bus.py changes will rebuild ALL services that include shared/).

### 3. Tail a build log
```bash
gcloud builds log <BUILD_ID> --region=asia-south1
```

### 4. Verify deployed image matches new build SHA
```bash
for j in nidp-amfi-nav-history nidp-fno-bhavcopy nidp-price-adjuster nidp-delivery; do
  img=$(gcloud run jobs describe $j --region=asia-south1 \
    --format='value(spec.template.spec.template.spec.containers[0].image)')
  echo "$j -> ${img##*:}"
done
```
Cross-check the SHA against the build IDs from step 2.

### 5. Manual trigger a run (for non-scheduled jobs)
```bash
gcloud run jobs execute nidp-amfi-nav-history --region=asia-south1 --async
gcloud run jobs execute nidp-price-adjuster   --region=asia-south1 --async
```

### 6. Check execution status
```bash
gcloud run jobs executions list --job=<job> --region=asia-south1 --limit=3 \
  --format='table(name,status.conditions[0].status,startTime,completionTime)'
```
Expect: `True` in the status column.

### 7. Confirm DB write succeeded
```sql
SELECT ingester, status, finished_at, target_date
  FROM nidp.job_log
 WHERE finished_at > NOW() - INTERVAL '4 hours'
 ORDER BY finished_at DESC LIMIT 20;
```
Expect: an `OK` row for each ingester run.

## Common failure modes and fixes

| Symptom | Cause | Fix |
|---|---|---|
| No build fired after push | Trigger's `includedFiles` doesn't match changed file path | Edit trigger or move the file |
| Build SUCCESS but image SHA on Job is older | Deploy step in cloudbuild-service.yaml silently failed (check the `deploy` step log) | Force-deploy: `gcloud run jobs update <job> --image=<new-sha> --region=asia-south1` |
| Execution shows `False` status | Job code is failing | Check `gcloud logging read` with `labels."run.googleapis.com/execution_name"=<exec>` |
| `job_log` row missing | Service didn't reach the writer (early crash) | Check stdout logs |
