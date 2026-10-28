import { ShieldCheck, Sparkles } from \"lucide-react\"

export function Header() {
  return (
    <header className=\"sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200/50\">
      <div className=\"max-w-[1600px] mx-auto px-6 py-4\">
        <div className=\"flex items-center justify-between\">
          <div className=\"flex items-center gap-3\">
            <div className=\"relative\">
              <div className=\"absolute inset-0 bg-gradient-to-r from-blue-600 to-indigo-600 rounded-lg blur opacity-75\"></div>
              <div className=\"relative bg-gradient-to-r from-blue-600 to-indigo-600 p-2 rounded-lg\">
                <ShieldCheck className=\"w-6 h-6 text-white\" />
              </div>
            </div>
            <div>
              <div className=\"flex items-center gap-2\">
                <h1 className=\"text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-700 bg-clip-text text-transparent\">ProofLine</h1>
                <Sparkles className=\"w-4 h-4 text-amber-500\" />
              </div>
              <p className=\"text-xs text-gray-500\">AI-Powered QA Inspector</p>
            </div>
          </div>
          <div className=\"flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-full border border-blue-200/50\">
            <div className=\"w-2 h-2 bg-emerald-500 rounded-full animate-pulse\"></div>
            <span className=\"text-xs font-medium text-blue-700\">AI Ready</span>
          </div>
        </div>
      </div>
    </header>
  )
}
