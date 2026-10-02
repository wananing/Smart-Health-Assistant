import type { FC } from 'react';
import { Footprints, Heart, Moon } from 'lucide-react';
import VitalCard from './VitalCard';
import { useTextScale } from '../../design/textScale';

const STEPS = 8542;
const STEP_GOAL = 10000;
const RING_CIRCUMFERENCE = 2 * Math.PI * 16;

const VitalsHero: FC = () => {
    const t = useTextScale();
    const percent = Math.min(100, Math.round((STEPS / STEP_GOAL) * 100));

    return (
        <section className="space-y-3">
            {/* Today's step goal: the headline number of the page */}
            <div className="rounded-card bg-gradient-to-br from-white to-brand-50 p-5 shadow-raised flex items-center gap-5">
                <div className="relative w-24 h-24 shrink-0" aria-label={`今日步数目标完成 ${percent}%`}>
                    <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                        <circle cx="18" cy="18" r="16" fill="none" strokeWidth="3" className="stroke-brand-100" />
                        <circle
                            cx="18" cy="18" r="16" fill="none" strokeWidth="3" strokeLinecap="round"
                            className="stroke-brand-600"
                            strokeDasharray={`${(percent / 100) * RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
                        />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <Footprints size={18} className="text-brand-700" />
                        <span className={`font-semibold text-brand-800 tabular-nums ${t.body}`}>{percent}%</span>
                    </div>
                </div>
                <div className="min-w-0">
                    <div className={`text-ink-600 ${t.body}`}>今日步数</div>
                    <div className="flex items-baseline gap-1.5">
                        <span className={`font-semibold text-ink-900 tabular-nums ${t.headline}`}>{STEPS.toLocaleString('zh-CN')}</span>
                        <span className={`text-ink-600 ${t.body}`}>步</span>
                    </div>
                    <div className={`text-ink-600 ${t.caption}`}>目标 {STEP_GOAL.toLocaleString('zh-CN')} 步，还差 {(STEP_GOAL - STEPS).toLocaleString('zh-CN')} 步</div>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
                <VitalCard
                    title="心率"
                    tone="danger"
                    icon={Heart}
                    value="72"
                    unit="次/分"
                    status="正常水平"
                />
                <VitalCard
                    title="昨晚睡眠"
                    tone="info"
                    icon={Moon}
                    value="7.5"
                    unit="小时"
                    status="深睡 2.5 小时"
                />
            </div>
        </section>
    );
};

export default VitalsHero;
