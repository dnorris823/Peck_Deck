# Add a user

This guide adds one person to Peck Deck. When it is done, they can open the web
app on their phone, see the feeders shared with them, and get bird alerts.

Peck Deck is a private system for a few people. The web app has no public
address. It runs on the gaming PC and only devices on the owner's tailnet can
reach it. So a new user needs two things: a place on the tailnet and an account
in the app.

The owner does part 1. The new user does part 2.

## Part 1: the owner

### Invite them to the tailnet

1. Open the Tailscale admin console and go to **Users**.
2. Select **Invite users**. Enter their email, or copy the invite link and send
   it to them.
3. Keep their role as **Member**. A member can use the tailnet but cannot change
   the access policy or remove devices.

The free Personal plan allows 6 users. Devices do not count against it.

The default access policy lets every member reach every device. That is the
intended setup here. Peck Deck trusts everyone on the tailnet.

### Create their app account

1. Open the web app and go to **More → Users**.
2. Select **Add user**. Enter their name and email, and set a temporary password.
3. Keep the role as **Viewer**. An owner can add users, reset passwords, and
   manage every feeder. One owner is enough.
4. Send them the temporary password and the app URL,
   `https://<pc>.<tailnet>.ts.net`.

### Share a feeder with them

A new user sees nothing until a feeder is shared with them. A user sees the
feeders they own and the feeders they are a member of. Alerts follow the same
rule.

If they will run their own feeder, follow `docs/feeder-onboarding.md`. Their
feeder is theirs from the start.

To let them see one of your feeders, add them as a member of it. The app has no
button for this yet
([Feeder settings can't share a feeder or change its location](https://github.com/dnorris823/Peck_Deck/issues/156)),
so use the API page on the gaming PC:

1. Open `http://localhost:8000/schema/swagger` on the gaming PC.
2. Run `POST /login` with your owner email and password. Copy `access_token`
   from the response.
3. Select **Authorize**, paste the token into **UserJWT**, and confirm.
4. Run `GET /users/` and note the new user's `id`.
5. Run `GET /devices/` and note the feeder's `id`.
6. Run `POST /devices/{device_id}/users` with that feeder `id` and the body
   `{"user_id": <their id>}`. A 204 means it worked.

To undo it, run `DELETE /devices/{device_id}/users/{uid}`.

## Part 2: the new user

### Get on the tailnet

1. Install the Tailscale app on your phone.
2. Open the invite link. Sign in with a Google, Apple, or Microsoft account.
3. Accept the invite. Your phone joins the tailnet.
4. Keep Tailscale connected. The app does not load without it.

If you already use Tailscale with your own tailnet, the Tailscale app can switch
between accounts. Peck Deck needs the account that accepted the invite.

### Sign in

1. Open the app URL in your phone's browser.
2. Sign in with your email and the temporary password.
3. Go to **More → Settings → Account** and change your password.

A sign-in lasts 30 days. Signing out signs you out on every device, not only
this one.

### Add it to your home screen

The app installs like a phone app.

- **Android, Chrome:** open the browser menu and select **Install app** or
  **Add to Home screen**.
- **iPhone, Safari:** tap **Share**, then **Add to Home Screen**. This step is
  required for alerts on iPhone, and it needs iOS 16.4 or later.

### Turn on alerts

Go to **More → Settings → Notifications**.

| Setting | What it does |
|---|---|
| Browser push, this device | Sends an alert to this phone. Turn it on separately on each phone or computer. |
| Email | Sends an alert to your email address. |
| Quiet interval | The shortest time between two alerts from the same feeder. It stops a long visit from sending many alerts. |
| Notify only for new species | Sends an alert only the first time a species appears. |

Turn on browser push from the home screen app, not from a browser tab. If the
switch says the browser cannot receive push, you opened the app from a browser
tab, or the phone is too old.

## The app

| Tab | What it shows |
|---|---|
| Latest | The newest sightings. New birds appear without a refresh. |
| Live | The feeder camera. "Live · relayed" means the video goes through the gaming PC, 1 to 3 seconds behind. That is normal on a phone. |
| Species | Every species seen at your feeders. |
| History | All sightings, with filters. |
| Feeders | Each feeder and whether it is online. |

The gaming PC names the species. It is often right and sometimes wrong. A
sighting named "Unknown" is a bird that no classifier could name.

## When it does not work

| Symptom | Cause |
|---|---|
| The page does not load | Tailscale is off on the phone, or the gaming PC is off. |
| The page loads, but there are no birds and no feeders | No feeder is shared with you yet. Ask the owner. |
| A feeder shows offline | That feeder's Pi has no power or no internet, or the gaming PC is off. The Pi keeps its photos and uploads them later. |
| Signed out with no warning | You signed out on another device, or the owner reset your password. Sign in again. |

## Remove a user

Remove them from the tailnet in the Tailscale admin console. That alone cuts
their access, because the app is only reachable on the tailnet. Their app
account and their feeders stay in the database.
