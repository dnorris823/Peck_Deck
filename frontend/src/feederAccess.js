// Who can see a feeder: its owner and its members, who are also its alert
// recipients. Feeder settings and the Users page both edit it, through
// GET, POST and DELETE /devices/{id}/users.
import { useCallback, useEffect, useState } from "react";
import { addFeederMember, fetchFeederAccess, removeFeederMember } from "./data.js";

/**
 * The `{ owner, members }` of each feeder in `deviceIds`, keyed by feeder id.
 * `share` and `unshare` change one membership, then refetch that feeder, and
 * reject with the server's error for the caller to show.
 */
export function useFeederAccess(deviceIds) {
  const key = deviceIds.join(",");
  const [access, setAccess] = useState(() => new Map());
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const ids = key ? key.split(",").map(Number) : [];
    Promise.all(ids.map((id) => fetchFeederAccess(id).then((a) => [id, a])))
      .then((entries) => {
        if (cancelled) return;
        setAccess(new Map(entries));
        setLoaded(true);
      })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [key]);

  const refetch = useCallback(async (deviceId) => {
    const a = await fetchFeederAccess(deviceId);
    setAccess((m) => new Map(m).set(deviceId, a));
  }, []);

  const share = useCallback(async (deviceId, who) => {
    await addFeederMember(deviceId, who);
    await refetch(deviceId);
  }, [refetch]);

  const unshare = useCallback(async (deviceId, userId) => {
    await removeFeederMember(deviceId, userId);
    await refetch(deviceId);
  }, [refetch]);

  return { access, loaded, error, share, unshare };
}

/** Whether the user may edit the feeder: its owner, or anyone with the owner role. */
export function canManageFeeder(device, me) {
  return me.role === "owner" || device.ownerId === me.id;
}
