import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2">
      <h1 className="text-lg font-semibold text-white">Not found</h1>
      <Link href="/" className="text-sm text-accent hover:underline">Back to overview</Link>
    </main>
  );
}
