"use client";

import dynamic from "next/dynamic";

// WebGL map must only render on the client.
const SchoolMap = dynamic(() => import("../components/SchoolMap"), {
  ssr: false,
});

export default function Page() {
  return <SchoolMap />;
}
