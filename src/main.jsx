import React from 'react'
import ReactDOM from 'react-dom/client'
import { ClerkProvider } from '@clerk/react'
import App from '@/App.jsx'
import '@/index.css'

const clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const auraApiUrl = import.meta.env.VITE_AURA_API_URL
const productUrl = `${window.location.origin}${import.meta.env.BASE_URL}`

const unavailable = (
  <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
    <section className="max-w-lg rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
      <h1 className="text-xl font-semibold">AURA is temporarily unavailable</h1>
      <p className="mt-3 text-sm text-slate-400">Please try again in a moment.</p>
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
  ) : unavailable
)
