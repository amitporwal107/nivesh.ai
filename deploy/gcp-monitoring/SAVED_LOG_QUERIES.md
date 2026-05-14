# Saved Log Queries — GCP Cloud Logging

Paste these into the Cloud Logging query editor (Logs Explorer).
Pin frequently-used queries via the "Save" button.

---

## nivesh-main-app

### All requests (last hour)
```
jsonPayload.application="nivesh-main-app"
jsonPayload.eventType="REQUEST"
```

### 5xx Errors
```
jsonPayload.application="nivesh-main-app"
jsonPayload.eventType="REQUEST"
jsonPayload.httpStatus>=500
```

### Slow requests (>3s)
```
jsonPayload.application="nivesh-main-app"
jsonPayload.eventType="REQUEST"
jsonPayload.responseTimeMs>3000
```

### Auth failures
```
jsonPayload.application="nivesh-main-app"
(jsonPayload.httpStatus=401 OR jsonPayload.httpStatus=403)
```

### Exceptions with stack traces
```
jsonPayload.application="nivesh-main-app"
jsonPayload.exceptionClass!=""
severity>=ERROR
```

### CAS parsing errors
```
jsonPayload.application="nivesh-main-app"
jsonPayload.msg=~"CAS"
severity>=ERROR
```

### Specific correlation ID trace
```
jsonPayload.application="nivesh-main-app"
jsonPayload.correlationId="REPLACE_WITH_CORRELATION_ID"
```

---

## nidp-console

### All job runs
```
jsonPayload.application="nidp-console"
jsonPayload.eventType=~"JOB_"
```

### Job failures
```
jsonPayload.application="nidp-console"
jsonPayload.eventType="JOB_FAILURE"
```

### Pipeline errors by job
```
jsonPayload.application="nidp-console"
severity>=ERROR
jsonPayload.jobName!=""
```

### Specific job trace (replace JOB_NAME)
```
jsonPayload.application="nidp-console"
jsonPayload.jobName="bulk_deals"
```

### Data validation events
```
jsonPayload.application="nidp-console"
jsonPayload.eventType="DATA_EVENT"
```

---

## admin-app

### All admin requests
```
jsonPayload.application="admin-app"
jsonPayload.eventType="REQUEST"
```

### Admin 5xx Errors
```
jsonPayload.application="admin-app"
jsonPayload.httpStatus>=500
```

### Audit actions
```
jsonPayload.application="admin-app"
(jsonPayload.eventType="AUDIT_ACTION"
 OR jsonPayload.eventType="CONFIG_CHANGE"
 OR jsonPayload.eventType="USER_MANAGEMENT")
```

### Admin auth failures
```
jsonPayload.application="admin-app"
(jsonPayload.httpStatus=401 OR jsonPayload.httpStatus=403)
```

### Config changes
```
jsonPayload.application="admin-app"
jsonPayload.eventType="CONFIG_CHANGE"
```

---

## Cross-app queries

### All CRITICAL logs across all apps
```
severity="CRITICAL"
(jsonPayload.application="nivesh-main-app"
 OR jsonPayload.application="nidp-console"
 OR jsonPayload.application="admin-app")
```

### All errors across all apps (last 15 min)
```
severity>=ERROR
(jsonPayload.application="nivesh-main-app"
 OR jsonPayload.application="nidp-console"
 OR jsonPayload.application="admin-app")
```
