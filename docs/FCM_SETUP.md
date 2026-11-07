# Firebase Cloud Messaging setup and device test

The API stores durable, user-scoped notifications in PostgreSQL and uses
Firebase Cloud Messaging (FCM) as the delivery transport for Android and iOS.
The notification inbox remains authoritative if a push is delayed or missed.
It contains only unopened notifications: opening one deletes it; otherwise it
remains until its expiry (90 days by default).

## Firebase project

1. Register the Android and iOS applications in the same Firebase project.
2. Add `google-services.json` to the Flutter Android app.
3. Add `GoogleService-Info.plist` to the Flutter iOS app.
4. Upload the APNs `.p8` key in Firebase for the iOS app.
5. Enable the Firebase Cloud Messaging HTTP v1 API.

## API credentials

From Firebase project settings, create a service-account private key for the
API. Never commit this JSON file. For local Docker development, place it at:

```text
secrets/firebase-service-account.json
```

Configure the API:

```dotenv
FCM_ENABLED=true
FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_CREDENTIALS_PATH=/app/secrets/firebase-service-account.json
FCM_ANDROID_CHANNEL_ID=321vegan_notifications
```

Then apply migrations and start the worker:

```bash
make migration-apply
make fcm-worker
```

Revision `b6e2f7c91a04` creates the three notification tables directly in their
final form, without read-state or per-entity deduplication columns. Apply it
before starting the updated API and worker.

## Flutter registration contract

After login, and whenever Firebase refreshes its registration token, call:

```http
POST /me/push-devices/
Authorization: Bearer <api-token>
Content-Type: application/json
```

```json
{
  "platform": "android",
  "installation_id": "the-firebase-installation-id",
  "token": "the-fcm-registration-token"
}
```

Use `platform: ios` on Apple devices. Pushes always target the FCM registration
`token` obtained by Flutter's `FirebaseMessaging.instance.getToken()`.
`installation_id` is optional but recommended to identify the existing device
record when its token changes; it is never used as the messaging destination.
This matches the app's token-based registration, without enabling Firebase's
separate FID-based messaging mode. Delete `/me/push-devices/{device_id}` during
logout or notification opt-out.

The current Firebase SDK warns that token targeting is deprecated. A future
move to FID targeting must update the app's messaging registration and the API
together; merely storing an installation ID does not enable that mode.

Older app builds may continue sending an `environment` field; it is ignored.
The registration response temporarily retains deprecated `provider` and
`environment` constants for response compatibility, but they are not stored.

## Inbox and acknowledgement contract

- `GET /me/notifications/?after_id=0&limit=100` returns the authenticated user's
  unexpired, unopened notifications in ascending ID order. `read_at` remains
  present as `null` for response compatibility; it is no longer stored.
- On opening a notification, call `PATCH /me/notifications/{notification_id}/read`
  with the bearer token and **no request body**. It deletes that user's
  notification and its delivery rows and returns **204 No Content**. The same
  empty response is returned for a missing ID or another user's ID, without
  deleting another user's data. Repeated acknowledgements are safe.
- Remove the acknowledged item from the app's local inbox. There is no API
  read-history list. Do not acknowledge merely on receipt of a push.
- If acknowledgement fails (for example, while offline), retain it for retry
  under the same user account. Opening locally cannot delete the server row
  until an acknowledgement succeeds; the idempotent endpoint makes retries safe.
- The cursor reports new notifications, not deletions. To reconcile deletion
  on another device, reload all pages from `after_id=0` and replace/reconcile
  the cached inbox, rather than only appending. Drop cached expired entries too.

For `error_report.handled`, each `handled: false → true` transition creates a
notification. Repeating `handled: true` creates none. Reopening and handling
again creates a new notification even if the previous occurrence is unread or
has already been deleted. The report row lock makes simultaneous handling
requests produce only one notification for that transition. There is no
per-entity or permanent deduplication key; future event producers must enforce
their own genuine state transition in the transaction.

## Production processes

Run the FCM worker as a permanent process alongside the API. The Compose setup
keeps it in the `fcm` profile so local development can start it explicitly with
`make fcm-worker`. Also schedule `make notifications-cleanup` once per day so
expired inbox and delivery rows do not accumulate indefinitely.

## End-to-end verification

1. Obtain an FCM registration token from a physical device.
2. Send a test message from the Firebase console.
3. Register the token with the API while logged in as a normal user.
4. Trigger and handle an error report for that user.
5. Confirm a `notifications` row and a `notification_deliveries` row exist.
6. Confirm the delivery becomes `sent` and stores the Firebase message ID.
7. Test foreground, background, terminated, tap, logout, and token-refresh flows.
8. Open the notification; confirm the acknowledgement returns 204 and both the
   notification and its deliveries disappear. Repeat the acknowledgement.
9. Repeat handling (no new notification), then reopen and handle the report
   again (a new notification). Also test while the previous occurrence is unread.

The push payload contains `notification_id`, the server-verified `user_id`,
`type`, and a JSON-encoded `data` field. Flutter should ignore a push whose
`user_id` does not match the currently authenticated account, then reconcile
accepted pushes with `GET /me/notifications/` after receiving or opening them.

## Consistency and retries

- Create notifications through `notification_service.create()`, in the same
  transaction as the domain change (`commit=False` when the caller commits).
  It locks the recipient before allocating the notification ID and holds the
  lock until commit. This makes per-user `after_id` polling safe against
  out-of-order commits. The domain row lock/state transition, not the generic
  notification service, prevents duplicate occurrences from repeated requests.
- The worker claims one delivery at a time. Each persisted attempt counts
  toward `FCM_MAX_ATTEMPTS`, including attempts interrupted by a worker crash.
  The processing timeout makes abandoned claims eligible for recovery.
- During a send, the worker holds locks on the device and delivery. Competing
  workers skip the locked delivery, and logout/token refresh/account changes
  wait for that send to finish. Each Firebase HTTP wait is limited to 15 seconds
  (SDK retries may extend the overall send). A cancelled or superseded claim
  cannot send; an expired notification or mismatched owner is also rejected.
- Acknowledgement cascades to outstanding deliveries. A worker whose claimed
  row has disappeared skips it. If a send is already in flight, deletion waits
  for its delivery lock; deletion cannot retract a push accepted by Firebase.
- A process crash after Firebase accepts a push but before the database commit
  can still cause redelivery. Flutter should deduplicate by `notification_id`.
  `sent` means Firebase accepted the request, not that the device displayed it.
- Logout cannot retract a push already accepted by Firebase. The `user_id`
  check protects app routing, not automatic OS notification display; keep
  sensitive details out of the visible push title/body.
- `fcm-worker-once` exits nonzero for a failed batch (for example, a database
  error). Individual Firebase errors are recorded as retry/failed deliveries,
  so inspect delivery status as well when testing.

## Automated tests

With the local API and PostgreSQL containers running:

```bash
make test-notifications
```

This runs the HTTP/unit tests and real PostgreSQL concurrency tests. The latter
create a uniquely named `notification_test_*` schema, use only that schema (no
fallback to application tables), and remove it afterwards. All Firebase sends
are mocked. Set `NOTIFICATION_TEST_DATABASE_URL` in the test process to use a
separate test database; otherwise these isolated schemas use the configured DB.

Plain `python -m unittest discover -s tests -v` runs the in-memory suite and skips
PostgreSQL tests unless `RUN_POSTGRES_NOTIFICATION_TESTS=1` is set.
