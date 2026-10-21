import { Brain, ArrowRight, ShieldCheck } from 'lucide-react';
import PlanStep from '@/components/aura/PlanStep';
import { workflowSteps } from './scenario.mjs';
const provided={draggableProps:{},dragHandleProps:{},innerRef:()=>{}};
export default function ShowcasePlan({onReview}) {
  return <section className="mx-auto max-w-2xl"><div className="mb-6"><h2 className="flex items-center gap-2 text-lg font-semibold"><Brain className="h-5 w-5 text-primary"/>Here’s how AURA plans to complete your task</h2><p className="mt-3 text-xs leading-6 text-muted-foreground">One prepared website-content workflow. Review the evidence and proposed result before starting the local playback.</p></div>{workflowSteps.map((step,index)=><PlanStep key={step.title} step={step} index={index} isLast={index===workflowSteps.length-1} provided={provided} readOnly/>)}<div className="mt-5 rounded-xl border border-white/10 p-4"><p className="flex gap-2 text-xs leading-6 text-muted-foreground"><ShieldCheck className="mt-1 h-4 w-4 shrink-0 text-emerald-300"/>Prepared demonstration. No client account is connected, no approval is recorded and no live content changes.</p><button type="button" onClick={onReview} className="ml-auto mt-4 flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white">Review before running<ArrowRight className="h-4 w-4"/></button></div></section>;
}
