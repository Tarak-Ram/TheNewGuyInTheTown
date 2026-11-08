"use client";

// Shown if a page crashes. The person gets a way forward, never a blank screen.
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <h1>Something went wrong</h1>
      <p role="alert">Sorry about that. Your details are saved. Please try again.</p>
      <p>
        <button onClick={reset}>Try again</button>
      </p>
      <p><a href="/">Go to the start</a></p>
    </>
  );
}
