import Link from "next/link";

export default function NotFound() {
  return (
    <div className="card" data-testid="not-found">
      <h1>Page not found</h1>
      <p>This page does not exist.</p>
      <Link href="/">Back to the portfolio</Link>
    </div>
  );
}
