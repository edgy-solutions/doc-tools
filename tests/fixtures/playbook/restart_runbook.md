Synthetic playbook fixture. Not a real runbook.

# Restart the ingest service

Use this when the ingest service stops draining its queue.

## Before you start

Confirm you hold the on-call role.

### Check the queue depth

Run the depth check and write down the number.

```bash
# this comment is not a heading
queue-depth --service ingest
```

### Check the last deploy

Note the image digest of the running release.

## Restart

### Drain

Stop new work from arriving.

### Roll the pods

Restart the pods one at a time.

## Verify

The depth falls to zero within ten minutes.

# Rotate the service token

#### Rotate

Issue a new token and update the secret by name.
