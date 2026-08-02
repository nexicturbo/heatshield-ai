import type { Metadata } from "next";
import { HeatShieldDashboard } from "./components/HeatShieldDashboard";

export const metadata: Metadata = {
  title: "HeatShield AI | Heat planning with visible evidence",
  description:
    "A Chicago demonstration with fictional planning scenarios, audited access data, and live National Weather Service context.",
};

export default function Home() {
  return <HeatShieldDashboard />;
}
