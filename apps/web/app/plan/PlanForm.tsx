"use client";

import type { PlanCreate } from "@schemas";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

type Props = { planId?: string; initial?: PlanCreate; demoHint?: boolean };

const field = { display: "block", width: "100%", padding: 8, marginTop: 4, boxSizing: "border-box" } as const;
const group = { marginBottom: 16 } as const;

async function errorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  if (typeof body?.detail === "string") return body.detail;
  if (res.status === 401) return "Please sign in first.";
  return "Something went wrong. Please try again.";
}

export default function PlanForm({ planId, initial, demoHint }: Props) {
  const router = useRouter();
  const [address, setAddress] = useState(initial?.office_address ?? "");
  const [place, setPlace] = useState(
    initial ? { lat: initial.office_lat, lng: initial.office_lng } : null,
  );
  const [addressMsg, setAddressMsg] = useState(initial ? "Address saved." : "");
  const [addressError, setAddressError] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function checkAddress() {
    setChecking(true);
    setAddressMsg("");
    setAddressError(false);
    const res = await fetch("/api/proxy/v1/places/validate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ address }),
    }).catch(() => null);
    setChecking(false);
    if (!res || !res.ok) {
      setPlace(null);
      setAddressError(true);
      setAddressMsg(res ? await errorText(res) : "Could not reach the service.");
      return;
    }
    const found = (await res.json()) as { formatted_address: string; lat: number; lng: number };
    setPlace({ lat: found.lat, lng: found.lng });
    setAddress(found.formatted_address);
    setAddressMsg("Address found on the map.");
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    if (!place) {
      setAddressError(true);
      setAddressMsg("Please check your office address first.");
      return;
    }
    const f = new FormData(e.currentTarget);
    const body: PlanCreate = {
      office_address: address,
      office_lat: place.lat,
      office_lng: place.lng,
      budget_min: Number(f.get("budget_min")),
      budget_max: Number(f.get("budget_max")),
      arrival_date: String(f.get("arrival_date")),
      needs: {
        food: f.get("food") as PlanCreate["needs"]["food"],
        commute_mode: f.get("commute_mode") as PlanCreate["needs"]["commute_mode"],
        pg_gender: f.get("pg_gender") as PlanCreate["needs"]["pg_gender"],
      },
    };
    if (body.budget_max < body.budget_min) {
      setError("Your highest budget must be at least your lowest budget.");
      return;
    }
    setSaving(true);
    const res = await fetch(planId ? `/api/proxy/v1/plans/${planId}` : "/api/proxy/v1/plans", {
      method: planId ? "PUT" : "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    if (!res || !res.ok) {
      setSaving(false);
      setError(res ? await errorText(res) : "Could not reach the service.");
      return;
    }
    const saved = (await res.json()) as { id: string };
    router.push(`/plan/${saved.id}`);
  }

  return (
    <form onSubmit={onSubmit}>
      <div style={group}>
        <label htmlFor="address">Office address</label>
        <input
          id="address"
          style={field}
          value={address}
          onChange={(e) => {
            setAddress(e.target.value);
            setPlace(null); // changed text must be checked again
            setAddressMsg("");
          }}
          required
          minLength={3}
        />
        <button type="button" onClick={checkAddress} disabled={checking || address.length < 3}>
          {checking ? "Checking..." : "Check address"}
        </button>
        {demoHint && (
          <p style={{ color: "#5c3b00" }}>
            Demo mode: try Wipro Circle, Cyber Towers, Mindspace, Microsoft, Financial District,
            Kondapur or Madhapur.
          </p>
        )}
        <p role={addressError ? "alert" : "status"} style={{ color: addressError ? "#b00020" : "#146c2e" }}>
          {addressMsg}
        </p>
      </div>

      <div style={group}>
        <label htmlFor="budget_min">Lowest monthly budget (Rs)</label>
        <input id="budget_min" name="budget_min" type="number" min={0} step={500} style={field}
          defaultValue={initial?.budget_min ?? 7000} required />
        <label htmlFor="budget_max">Highest monthly budget (Rs)</label>
        <input id="budget_max" name="budget_max" type="number" min={0} step={500} style={field}
          defaultValue={initial?.budget_max ?? 14000} required />
      </div>

      <div style={group}>
        <label htmlFor="arrival_date">When do you arrive?</label>
        <input id="arrival_date" name="arrival_date" type="date" style={field}
          defaultValue={initial?.arrival_date} required />
      </div>

      <div style={group}>
        <label htmlFor="food">Food</label>
        <select id="food" name="food" style={field} defaultValue={initial?.needs.food ?? "any"}>
          <option value="any">No preference</option>
          <option value="veg">Vegetarian</option>
          <option value="non_veg">Non-vegetarian</option>
        </select>
        <label htmlFor="commute_mode">How will you travel to work?</label>
        <select id="commute_mode" name="commute_mode" style={field}
          defaultValue={initial?.needs.commute_mode ?? "any"}>
          <option value="any">Not sure</option>
          <option value="bike">Bike</option>
          <option value="car">Car or cab</option>
          <option value="public">Bus or metro</option>
        </select>
        <label htmlFor="pg_gender">PG type</label>
        <select id="pg_gender" name="pg_gender" style={field} defaultValue={initial?.needs.pg_gender ?? "any"}>
          <option value="any">Any</option>
          <option value="men">Men only</option>
          <option value="women">Women only</option>
        </select>
      </div>

      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
      <button type="submit" disabled={saving}>
        {saving ? "Saving..." : planId ? "Save and see areas" : "Find areas"}
      </button>
    </form>
  );
}
