"use client";

import { Suspense, use } from "react";

import { Loading } from "../../../components/ui";
import { Workspace } from "../../../components/workspace/Workspace";

export default function DecisionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Suspense fallback={<Loading label="Loading the decision" />}>
      <Workspace id={id} />
    </Suspense>
  );
}
