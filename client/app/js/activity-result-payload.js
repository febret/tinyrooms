/** Convert an activity bridge response into store result payload fields. */
export function activityResultPayload(response) {
  const payload = { activity: response?.activity || null };
  if (Array.isArray(response?.inventory)) payload.inventory = response.inventory;
  if (response?.user && typeof response.user === "object") payload.user = response.user;
  return payload;
}
