import React from 'react'
import ReactDOM from 'react-dom/client'
import App from '@/App.jsx'
import '@/index.css'
import { ClerkProvider } from '@clerk/react'

const clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const auraApiUrl = import.meta.env.VITE_AURA_API_URL
const productUrl = `${window.location.origin}${import.meta.env.BASE_URL}`

const missingClerk = (
  <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
    <section className="max-w-lg rounded-2xl border border-white/10 bg-white/5 p-8">
      <h1 className="text-xl font-semibold">AURA authentication is not configured</h1>
      <p className="mt-3 text-sm text-slate-400">Add VITE_CLERK_PUBLISHABLE_KEY and VITE_AURA_API_URL to the frontend deployment environment.</p>
    </section>
  </main>
)

ReactDOM.createRoot(document.getElementById('root')).render(
  clerkPublishableKey && auraApiUrl ? (
    <ClerkProvider
      publishableKey={clerkPublishableKey}
      afterSignOutUrl={productUrl}
      signInFallbackRedirectUrl={productUrl}
      signUpFallbackRedirectUrl={productUrl}
    >
      <App />
    </ClerkProvider>
  ) : missingClerk
)
