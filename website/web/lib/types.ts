// One row of public/data/schools.json (built by website/pipeline/build_dataset.py).
export type School = {
  i: string;           // NCES school id
  n: string;           // name
  s: string;           // state (USPS code)
  c: string;           // county FIPS
  ci: string;          // city
  a?: string;          // street address
  z?: string;          // ZIP
  d?: string;          // district (public only)
  lv: string;          // elementary | middle | high | combined | other
  e: number | null;    // enrollment
  ph?: string;         // phone
  tf?: number | null;  // teachers (FTE)
  gl?: string;         // lowest grade offered ("" when unknown)
  gh?: string;         // highest grade offered
  ch?: string;         // charter Yes/No (public only)
  pv?: 1;              // private school (PSS); absent for public
  w: 0 | 1;            // has a matched English Wikipedia article
  wt?: string;         // that article's title (when w = 1)
  x: number;           // longitude
  y: number;           // latitude
};
