"use client";

import { use } from "react";

import { BriefView } from "../../../components/brief/BriefView";
import { ErrorBox, Loading } from "../../../components/ui";
import { api } from "../../../lib/api";
import { useIdentity } from "../../../lib/identity";
import { useResource } from "../../../lib/useResource";

export default function BriefPage({ params }: { params: Promise<{ briefId: string }> }) {
  const { briefId } = use(params);
  const { me, ready } = useIdentity();
  const res = useResource(() => api.brief(briefId), [briefId, me?.id], ready && !!me);
  if (!ready || (res.loading && !res.data)) return <Loading label="Loading the brief" />;
  if (res.error) return <ErrorBox error={res.error} onRetry={res.reload} />;
  if (!res.data) return <Loading label="Loading the brief" />;
  return <BriefView brief={res.data} />;
}
