"use client";

import { useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, GeoJsonLayer } from "@deck.gl/layers";
import { FlyToInterpolator } from "@deck.gl/core";
import { Map as BaseMap } from "react-map-gl/maplibre";
import * as topojson from "topojson-client";
import Link from "next/link";
import ContributorPanel from "./ContributorPanel";
import MyContributions from "./MyContributions";
import { supabase } from "../lib/supabase";
import type { School } from "../lib/types";
import "maplibre-gl/dist/maplibre-gl.css";

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

const INITIAL_VIEW_STATE = {
  longitude: -98.5,
  latitude: 39.5,
  zoom: 3.6,
  pitch: 0,
  bearing: 0,
};

// Zoom level-of-detail thresholds.
const STATE_MAX = 5; // zoom < 5      -> state choropleth
const COUNTY_MAX = 7.5; // 5..7.5     -> county choropleth
// zoom >= 7.5 -> individual school points
const POINTS_LOAD_AT = 6.8; // lazy-load the big point file a bit early

const NO_DATA: [number, number, number] = [210, 216, 224];

// Coverage ramp (RdYlGn): low % = red "data desert", high % = green.
const RAMP: [number, [number, number, number]][] = [
  [0.03, [165, 0, 38]],
  [0.06, [215, 48, 39]],
  [0.1, [252, 141, 89]],
  [0.16, [254, 224, 139]],
  [0.25, [166, 217, 106]],
  [0.4, [102, 189, 99]],
];
// School-level filter. Coverage differs a lot by level (high schools ~54%,
// elementary/middle ~1%), so the color ramp is rescaled per level.
const LEVELS: { key: string; label: string; scale: number }[] = [
  { key: "all", label: "All", scale: 1 },
  { key: "high", label: "High", scale: 2 },
  { key: "middle", label: "Middle", scale: 0.15 },
  { key: "elementary", label: "Elementary", scale: 0.15 },
  { key: "other", label: "Unknown Grades", scale: 0.4 },
];
function covColor(frac: number, scale = 1): [number, number, number] {
  for (const [b, c] of RAMP) if (frac < b * scale) return c;
  return [26, 152, 80];
}
const pctLabel = (v: number) => `${+(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`;

const NAME2ABBR: Record<string, string> = {
  Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA",
  Colorado: "CO", Connecticut: "CT", Delaware: "DE", Florida: "FL", Georgia: "GA",
  Hawaii: "HI", Idaho: "ID", Illinois: "IL", Indiana: "IN", Iowa: "IA",
  Kansas: "KS", Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD",
  Massachusetts: "MA", Michigan: "MI", Minnesota: "MN", Mississippi: "MS",
  Missouri: "MO", Montana: "MT", Nebraska: "NE", Nevada: "NV",
  "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
  "North Carolina": "NC", "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK",
  Oregon: "OR", Pennsylvania: "PA", "Rhode Island": "RI", "South Carolina": "SC",
  "South Dakota": "SD", Tennessee: "TN", Texas: "TX", Utah: "UT", Vermont: "VT",
  Virginia: "VA", Washington: "WA", "West Virginia": "WV", Wisconsin: "WI",
  Wyoming: "WY", "District of Columbia": "DC",
  // territories, as named in us-atlas
  "Puerto Rico": "PR", Guam: "GU", "American Samoa": "AS",
  "United States Virgin Islands": "VI", "Commonwealth of the Northern Mariana Islands": "MP",
};

type Agg = Record<string, [number, number]>; // key -> [total, has]
type AggByLevel = Record<string, Agg>; // level -> key -> [total, has]
type FC = { type: "FeatureCollection"; features: any[] };

export default function SchoolMap() {
  const [view, setView] = useState<any>(INITIAL_VIEW_STATE);
  const [stateAgg, setStateAgg] = useState<Agg>({});
  const [countyAgg, setCountyAgg] = useState<Agg>({});
  const [stateByLevel, setStateByLevel] = useState<AggByLevel>({});
  const [countyByLevel, setCountyByLevel] = useState<AggByLevel>({});
  const [level, setLevel] = useState("all");
  const [statesGeo, setStatesGeo] = useState<FC | null>(null);
  const [countiesGeo, setCountiesGeo] = useState<FC | null>(null);
  const [points, setPoints] = useState<School[] | null>(null);
  const [loadingPoints, setLoadingPoints] = useState(false);
  const [selected, setSelected] = useState<School | null>(null);
  const [query, setQuery] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [expanded, setExpanded] = useState<School[] | null>(null);
  const [showAccount, setShowAccount] = useState(false);
  const [contribCount, setContribCount] = useState<number | null>(null);

  const zoom: number = view.zoom;
  const showStates = zoom < STATE_MAX;
  const showCounties = zoom >= STATE_MAX && zoom < COUNTY_MAX;
  const showPoints = zoom >= COUNTY_MAX;
  // dot size grows as you zoom into a city/street (px)
  const ptRadius = Math.min(16, Math.max(3, (zoom - 6.5) * 3));

  // total contributions so far (Supabase count, or this browser's drafts as a fallback).
  // The count comes from a security-definer function: anonymous visitors can't
  // read the contributions table itself (it holds contributors' contact info).
  function loadContribCount() {
    if (supabase) {
      supabase.rpc("contribution_count").then(({ data, error }) => {
        if (!error && typeof data === "number") setContribCount(data);
        else setContribCount(localContribCount());
      });
    } else {
      setContribCount(localContribCount());
    }
  }

  // small aggregate files + basemap geometry on mount
  useEffect(() => {
    loadContribCount();
    fetch("/data/state_coverage.json").then((r) => r.json()).then(setStateAgg);
    fetch("/data/county_coverage.json").then((r) => r.json()).then(setCountyAgg);
    fetch("/data/state_coverage_by_level.json").then((r) => r.json()).then(setStateByLevel);
    fetch("/data/county_coverage_by_level.json").then((r) => r.json()).then(setCountyByLevel);
    fetch("https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json")
      .then((r) => r.json())
      .then((us) => setStatesGeo(topojson.feature(us, us.objects.states) as any));
    fetch("https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json")
      .then((r) => r.json())
      .then((us) => setCountiesGeo(topojson.feature(us, us.objects.counties) as any));
  }, []);

  // load the full point file (used by the map at high zoom AND by search)
  function loadPoints() {
    if (points || loadingPoints) return;
    setLoadingPoints(true);
    fetch("/data/schools.json")
      .then((r) => r.json())
      .then((d: School[]) => setPoints(d))
      .finally(() => setLoadingPoints(false));
  }
  useEffect(() => {
    if (zoom >= POINTS_LOAD_AT) loadPoints();
  }, [zoom]); // eslint-disable-line react-hooks/exhaustive-deps

  // search: token (AND) match across name + city + state, grouped by school name
  // so common names ("Lincoln Elementary") don't bury distinct ones
  // ("Abraham Lincoln Elementary").
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2 || !points) return [];
    const tokens = q.split(/\s+/).filter(Boolean);
    const byName = new Map<string, School[]>();
    for (const s of points) {
      const hay = `${s.n} ${s.ci} ${s.s}`.toLowerCase();
      if (!tokens.every((t) => hay.includes(t))) continue;
      const arr = byName.get(s.n);
      if (arr) arr.push(s);
      else byName.set(s.n, [s]);
    }
    const list = [...byName.entries()].map(([name, schools]) => {
      const nl = name.toLowerCase();
      let score = 4;
      if (nl === q) score = 0;
      else if (nl.startsWith(q)) score = 1;
      else if (tokens.every((t) => nl.includes(t))) score = 2;
      else if (nl.includes(tokens[0])) score = 3;
      return { name, schools, score };
    });
    list.sort((a, b) =>
      a.score - b.score || a.name.length - b.name.length || b.schools.length - a.schools.length
    );
    return list.slice(0, 15);
  }, [query, points]);

  function pick(s: School) {
    setView((v: any) => ({
      ...v, longitude: s.x, latitude: s.y, zoom: 11,
      transitionDuration: 800, transitionInterpolator: new FlyToInterpolator(),
    }));
    setSelected(s);
    setQuery(""); setSearchFocused(false);
  }

  // aggregates and points for the selected level ("all" = everything)
  const scale = LEVELS.find((l) => l.key === level)?.scale ?? 1;
  const stateView: Agg = level === "all" ? stateAgg : stateByLevel[level] ?? {};
  const countyView: Agg = level === "all" ? countyAgg : countyByLevel[level] ?? {};
  const levelPoints = useMemo(
    () => (points && level !== "all" ? points.filter((p) => p.lv === level) : points),
    [points, level]
  );

  const national = useMemo(() => {
    let total = 0, has = 0;
    for (const k in stateView) { total += stateView[k][0]; has += stateView[k][1]; }
    return { total, has, missing: total - has, pct: total ? (100 * has) / total : 0 };
  }, [stateView]);

  function flyTo(info: any, z: number) {
    if (!info?.coordinate) return;
    const [longitude, latitude] = info.coordinate;
    setView((v: any) => ({
      ...v, longitude, latitude, zoom: z,
      transitionDuration: 700, transitionInterpolator: new FlyToInterpolator(),
    }));
  }

  const layers = [
    statesGeo &&
      new GeoJsonLayer({
        id: "states",
        data: statesGeo as any,
        visible: showStates,
        stroked: true, filled: true,
        getFillColor: (f: any) => {
          const a = stateView[NAME2ABBR[f.properties.name]];
          return a && a[0] ? [...covColor(a[1] / a[0], scale), 200] : [...NO_DATA, 90];
        },
        getLineColor: [255, 255, 255, 230],
        getLineWidth: 1, lineWidthUnits: "pixels",
        pickable: true,
        onClick: (info) => flyTo(info, 5.6),
        updateTriggers: { getFillColor: [stateView, scale] },
      }),
    countiesGeo &&
      new GeoJsonLayer({
        id: "counties",
        data: countiesGeo as any,
        visible: showCounties,
        stroked: true, filled: true,
        getFillColor: (f: any) => {
          const a = countyView[f.id];
          return a && a[0] ? [...covColor(a[1] / a[0], scale), 205] : [...NO_DATA, 70];
        },
        getLineColor: [255, 255, 255, 200],
        getLineWidth: 0.5, lineWidthUnits: "pixels",
        pickable: true,
        onClick: (info) => flyTo(info, 8.5),
        updateTriggers: { getFillColor: [countyView, scale] },
      }),
    levelPoints &&
      new ScatterplotLayer<School>({
        id: "schools",
        data: levelPoints,
        visible: showPoints,
        getPosition: (d) => [d.x, d.y],
        getFillColor: (d) => (d.w ? [34, 197, 94] : [239, 68, 68]),
        getRadius: ptRadius,
        radiusUnits: "pixels",
        radiusMinPixels: 2,
        opacity: 0.9, pickable: true,
        onClick: (info) => setSelected((info.object as School) ?? null),
        updateTriggers: { getRadius: ptRadius },
      }),
    // enlarged, ringed highlight for the currently selected school
    selected &&
      new ScatterplotLayer<School>({
        id: "selected-school",
        data: [selected],
        getPosition: (d) => [d.x, d.y],
        getFillColor: (d) => (d.w ? [34, 197, 94] : [239, 68, 68]),
        getRadius: ptRadius + 5,
        radiusUnits: "pixels",
        stroked: true,
        getLineColor: [255, 255, 255, 255],
        lineWidthUnits: "pixels",
        getLineWidth: 2.5,
        pickable: false,
        updateTriggers: { getPosition: selected.i, getRadius: ptRadius },
      }),
  ].filter(Boolean);

  return (
    <div className="app">
      <DeckGL
        viewState={view}
        onViewStateChange={(e: any) => setView(e.viewState)}
        controller={true}
        layers={layers as any}
        getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
        getTooltip={({ object, layer }: any) => {
          if (!object) return null;
          if (layer?.id === "schools") {
            const s = object as School;
            return tip(`<b>${s.n}</b><br/>${s.w ? "✓ has Wikipedia" : "✗ no Wikipedia"}`);
          }
          const isState = layer?.id === "states";
          const name = object.properties?.name + (isState ? "" : " County");
          const a = isState ? stateView[NAME2ABBR[object.properties.name]] : countyView[object.id];
          if (!a || !a[0]) return tip(`<b>${name}</b><br/>no data`);
          const pct = ((100 * a[1]) / a[0]).toFixed(1);
          return tip(
            `<b>${name}</b><br/>${pct}% on Wikipedia<br/>` +
              `<span style="color:#8b9bb0">${a[1].toLocaleString()} of ${a[0].toLocaleString()} schools</span>`
          );
        }}
      >
        <BaseMap mapStyle={MAP_STYLE} />
      </DeckGL>

      <header className="topbar">
        <div className="brand">
          SchoolData
          <span className="tagline">Make every school visible.</span>
        </div>

        <div className="search">
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); setExpanded(null); }}
            onFocus={() => { setSearchFocused(true); loadPoints(); }}
            onBlur={() => setTimeout(() => setSearchFocused(false), 150)}
            placeholder="🔍  Find a school by name or city…"
          />
          {searchFocused && query.trim().length >= 2 && (
            <div className="search-results">
              {!points || loadingPoints ? (
                <div className="search-empty">Loading schools…</div>
              ) : expanded ? (
                <>
                  <button className="search-back" onMouseDown={(e) => { e.preventDefault(); setExpanded(null); }}>
                    ‹ {expanded[0].n} — pick a location
                  </button>
                  {expanded.map((s) => (
                    <button key={s.i} className="search-row" onMouseDown={() => pick(s)}>
                      <span className={`sdot ${s.w ? "g" : "r"}`} />
                      <span className="sname">{[s.ci, s.s].filter(Boolean).join(", ")}</span>
                    </button>
                  ))}
                </>
              ) : groups.length === 0 ? (
                <div className="search-empty">No match for “{query}”.</div>
              ) : (
                groups.map((g) =>
                  g.schools.length === 1 ? (
                    <button key={g.name} className="search-row" onMouseDown={() => pick(g.schools[0])}>
                      <span className={`sdot ${g.schools[0].w ? "g" : "r"}`} />
                      <span className="sname">{g.name}</span>
                      <span className="sloc">{[g.schools[0].ci, g.schools[0].s].filter(Boolean).join(", ")}</span>
                    </button>
                  ) : (
                    <button key={g.name} className="search-row" onMouseDown={(e) => { e.preventDefault(); setExpanded(g.schools); }}>
                      <span className="sdot multi" />
                      <span className="sname">{g.name}</span>
                      <span className="scount">{g.schools.length} schools ›</span>
                    </button>
                  )
                )
              )}
            </div>
          )}
        </div>

        <Link href="/about" className="about-link" style={{ marginLeft: "auto" }}>
          About
        </Link>
        <button
          className="account-btn" style={{ marginLeft: 0 }}
          onClick={() => { setSelected(null); setShowAccount(true); loadPoints(); }}
        >
          My contributions
        </button>
      </header>

      <div className="stats">
        <div className="stat">
          <div className="v">{national.total.toLocaleString()}</div>
          <div className="k">
            {level === "all" ? "US K-12 schools" : `US ${LEVELS.find((l) => l.key === level)?.label.toLowerCase()} schools`}
          </div>
        </div>
        <div className="stat">
          <div className="v red">{national.missing.toLocaleString()}</div>
          <div className="k">NOT on Wikipedia</div>
        </div>
        <div className="stat">
          <div className="v green">{national.pct.toFixed(1)}%</div>
          <div className="k">ON Wikipedia</div>
        </div>
        <div className="stat">
          <div className="v blue">{contribCount == null ? "—" : contribCount.toLocaleString()}</div>
          <div className="k">Contributions to SchoolData</div>
        </div>
      </div>

      <div className="filters level-filter">
        {LEVELS.map((l) => (
          <button
            key={l.key}
            className={level === l.key ? "active" : ""}
            onClick={() => setLevel(l.key)}
          >
            {l.label}
          </button>
        ))}
      </div>

      <div className="legend">
        {showPoints ? (
          <>
            <div className="row">
              <span className="dot" style={{ background: "#ef4444" }} /> No article
            </div>
            <div className="row">
              <span className="dot" style={{ background: "#22c55e" }} /> Has article
            </div>
          </>
        ) : (
          <>
            <div className="legend-title">% of schools with a Wikipedia article</div>
            <div className="ramp">
              {[
                ...RAMP.map(([, c], i) => [
                  pctLabel(i ? RAMP[i - 1][0] * scale : 0), `rgb(${c.join(",")})`,
                ]),
                [`${pctLabel(RAMP[RAMP.length - 1][0] * scale)}+`, "#1a9850"],
              ].map(([lbl, c]) => (
                <div key={lbl} className="swatch">
                  <span style={{ background: c as string }} />
                  <small>{lbl}</small>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {selected && (
        <ContributorPanel school={selected} onClose={() => { setSelected(null); loadContribCount(); }} />
      )}
      {showAccount && (
        <MyContributions
          onClose={() => setShowAccount(false)}
          onOpenSchool={(s) => {
            // a saved contribution carries only a snapshot; open the full record
            setShowAccount(false);
            pick(points?.find((p) => p.i === s.i) ?? s);
          }}
        />
      )}
    </div>
  );
}

function localContribCount(): number {
  let n = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith("contrib:")) n++;
  }
  return n;
}

function tip(html: string) {
  return {
    html,
    style: {
      background: "#ffffff", color: "#1a2433", fontSize: "12px",
      padding: "6px 9px", borderRadius: "7px", border: "1px solid #d9e0ea",
      boxShadow: "0 4px 16px rgba(20,33,61,0.16)",
    },
  };
}
