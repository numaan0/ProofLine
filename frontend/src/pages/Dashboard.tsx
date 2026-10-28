import { useState } from \"react\"
import { Header } from \"../components/layout/Header\"
import { motion } from \"framer-motion\"
import { FileText, Image as ImageIcon, Sparkles } from \"lucide-react\"
import { Button } from \"../components/ui/Button\"

export default function Dashboard() {
  const [workOrder, setWorkOrder] = useState(\"\")
  const [images, setImages] = useState<File[]>([])

  return (
    <div className=\"min-h-screen bg-gradient-to-br from-gray-50 via-white to-blue-50/30\">
      <Header />
      <main className=\"max-w-[1600px] mx-auto px-6 py-8\">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className=\"mb-8\"
        >
          <h2 className=\"text-3xl font-bold text-gray-900 mb-2\">Verify Work Completion</h2>
          <p className=\"text-gray-600\">Upload your work order checklist and site photos. ProofLine will inspect and verify each item.</p>
        </motion.div>

        <div className=\"grid grid-cols-12 gap-6\">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className=\"col-span-12 lg:col-span-4\"
          >
            <div className=\"bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-200/50 overflow-hidden\">
              <div className=\"p-6 border-b border-gray-100\">
                <div className=\"flex items-center gap-2 mb-2\">
                  <FileText className=\"w-5 h-5 text-blue-600\" />
                  <h3 className=\"text-lg font-semibold text-gray-900\">Work Order</h3>
                </div>
                <p className=\"text-sm text-gray-500\">Paste your checklist items</p>
              </div>
              <div className=\"p-6\">
                <textarea
                  value={workOrder}
                  onChange={(e) => setWorkOrder(e.target.value)}
                  placeholder=\"Enter tasks one per line:\n- Install 2 outlet covers\n- Seal bathroom edges\n- Repaint wall\"
                  className=\"w-full h-64 px-4 py-3 rounded-xl border border-gray-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none resize-none text-sm leading-relaxed transition-all\"
                />
                <div className=\"mt-6\">
                  <div className=\"flex items-center gap-2 mb-3\">
                    <ImageIcon className=\"w-5 h-5 text-indigo-600\" />
                    <h3 className=\"text-lg font-semibold text-gray-900\">Site Photos</h3>
                  </div>
                  <div className=\"border-2 border-dashed border-gray-300 rounded-xl p-8 text-center hover:border-blue-400 hover:bg-blue-50/30 transition-all cursor-pointer\">
                    <ImageIcon className=\"w-12 h-12 text-gray-400 mx-auto mb-3\" />
                    <p className=\"text-sm font-medium text-gray-700 mb-1\">Drop photos here or click to upload</p>
                    <p className=\"text-xs text-gray-500\">PNG, JPG, JPEG up to 10MB</p>
                  </div>
                </div>
                <Button className=\"w-full mt-6\" size=\"lg\">
                  <Sparkles className=\"w-4 h-4 mr-2\" />
                  Run AI Inspection
                </Button>
              </div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className=\"col-span-12 lg:col-span-8\"
          >
            <div className=\"bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-200/50 h-full min-h-[600px] flex items-center justify-center\">
              <div className=\"text-center p-12\">
                <div className=\"w-20 h-20 bg-gradient-to-br from-blue-100 to-indigo-100 rounded-2xl flex items-center justify-center mx-auto mb-4\">
                  <ShieldCheck className=\"w-10 h-10 text-blue-600\" />
                </div>
                <h3 className=\"text-xl font-semibold text-gray-900 mb-2\">Ready to Inspect</h3>
                <p className=\"text-gray-500 max-w-md\">Add your work order and photos, then run the AI inspection to see detailed results with visual evidence.</p>
              </div>
            </div>
          </motion.div>
        </div>
      </main>
    </div>
  )
}
