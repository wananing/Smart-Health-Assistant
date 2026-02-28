import { useState } from 'react';
import type { FC } from 'react';
import {
    Stethoscope, ShieldCheck, Eye, EyeOff, ScanLine, FileText,
    TrendingDown, Calendar, MapPin, Building2, ArrowRight
} from 'lucide-react';
import type { ChatCardPayload } from '../../types';
import { ModeWelcomeCard, ModeExitCard } from './ModeContextCards';

// ─── shared sub-types ───────────────────────────────────────────────────────
interface InsuranceUser { name?: string; region?: string; insurance_type?: string; }
interface ClinicData { summary?: string; departments?: string[]; severity?: 'low' | 'medium' | 'high'; }
interface ReportData { title?: string; hospital?: string; date?: string; isAbnormal?: boolean; status?: string; }

interface ExpenseRecord {
    date: string; hospital: string; department: string;
    amount: number; self_pay: number; reimbursed: number; category: string;
}
interface PaymentRecord {
    year_month: string; individual: number; employer: number; total: number; status: string;
}
interface DesignatedHospital { name: string; level: string; type: string; }

// ─── 1. Insurance Balance Card ───────────────────────────────────────────────
const InsuranceBalanceCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const [showBalance, setShowBalance] = useState(true);
    const user = data.user as InsuranceUser | undefined;
    const personalAccount = (data.personal_account as number) ?? 2458.32;
    const medicalSavings = (data.medical_savings as number) ?? 12800.00;
    const lastDeposit = (data.last_month_deposit as number) ?? 320.00;
    const updatedAt = (data.updated_at as string) ?? '';
    return (
        <div className="bg-gradient-to-br from-blue-600 to-cyan-500 rounded-2xl p-5 text-white relative overflow-hidden shadow-lg shadow-blue-100">
            <div className="absolute -top-4 -right-4 opacity-10"><ShieldCheck size={100} /></div>
            <div className="flex items-center gap-1.5 text-blue-100 text-xs mb-1 tracking-widest">
                <ShieldCheck size={12} /> 国家医保电子凭证
            </div>
            <div className="text-base font-bold mb-4">
                {user?.region ?? '北京市'} · {user?.insurance_type ?? '城镇职工医保'}
            </div>

            {/* Balance row */}
            <div className="flex items-end justify-between mb-4">
                <div>
                    <div className="text-blue-100 text-xs flex items-center gap-2 mb-1">
                        个人账户余额（元）
                        <button onClick={() => setShowBalance(v => !v)} className="hover:text-white transition-colors">
                            {showBalance ? <Eye size={14} /> : <EyeOff size={14} />}
                        </button>
                    </div>
                    <div className="text-4xl font-black tabular-nums leading-none">
                        {showBalance ? personalAccount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) : '****.**'}
                    </div>
                </div>
                <div className="bg-white/20 backdrop-blur p-3 rounded-xl flex flex-col items-center gap-1 cursor-pointer hover:bg-white/30 transition-colors">
                    <ScanLine size={20} className="text-white" />
                    <span className="text-[10px] font-bold">去支付</span>
                </div>
            </div>

            {/* Stats row */}
            <div className="flex gap-3">
                <div className="flex-1 bg-white/15 rounded-xl p-2.5">
                    <div className="text-blue-100 text-[10px] mb-0.5">统筹可用</div>
                    <div className="font-black text-sm tabular-nums">
                        {showBalance ? `¥${medicalSavings.toLocaleString('zh-CN')}` : '¥****'}
                    </div>
                </div>
                <div className="flex-1 bg-white/15 rounded-xl p-2.5">
                    <div className="text-blue-100 text-[10px] mb-0.5">上月入账</div>
                    <div className="font-black text-sm tabular-nums">¥{lastDeposit.toFixed(2)}</div>
                </div>
                {updatedAt && (
                    <div className="flex-1 bg-white/15 rounded-xl p-2.5">
                        <div className="text-blue-100 text-[10px] mb-0.5">更新日期</div>
                        <div className="font-black text-[11px]">{updatedAt}</div>
                    </div>
                )}
            </div>
        </div>
    );
};

// ─── 2. Expenses Card (消费明细) ─────────────────────────────────────────────
const InsuranceExpensesCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const records = (data.records as ExpenseRecord[]) ?? [];
    const totalAmt = (data.total_amount as number) ?? 0;
    const totalSelf = (data.total_self_pay as number) ?? 0;
    const totalReimb = (data.total_reimbursed as number) ?? 0;
    const reimbRate = totalAmt > 0 ? Math.round((totalReimb / totalAmt) * 100) : 0;

    return (
        <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            {/* Header */}
            <div className="bg-gradient-to-r from-indigo-500 to-blue-500 px-4 py-3 flex items-center justify-between">
                <div className="flex items-center gap-2 text-white">
                    <TrendingDown size={16} />
                    <span className="font-bold text-sm">医保消费明细</span>
                </div>
                <span className="text-blue-100 text-xs">近 {(data.period_months as number) ?? 3} 个月</span>
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-3 divide-x divide-slate-100 border-b border-slate-100">
                <div className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 mb-0.5">总费用</div>
                    <div className="font-black text-sm text-slate-800 tabular-nums">¥{totalAmt.toFixed(0)}</div>
                </div>
                <div className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 mb-0.5">自付</div>
                    <div className="font-black text-sm text-rose-500 tabular-nums">¥{totalSelf.toFixed(0)}</div>
                </div>
                <div className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 mb-0.5">报销率</div>
                    <div className="font-black text-sm text-emerald-500 tabular-nums">{reimbRate}%</div>
                </div>
            </div>

            {/* Records list */}
            <div className="divide-y divide-slate-50 max-h-52 overflow-y-auto">
                {records.map((r, i) => (
                    <div key={i} className="flex items-center px-4 py-3 gap-3">
                        <div className="w-8 h-8 bg-indigo-50 text-indigo-500 rounded-xl flex items-center justify-center shrink-0">
                            <Building2 size={14} />
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="text-xs font-bold text-slate-700 truncate">{r.hospital}</div>
                            <div className="text-[10px] text-slate-400">{r.department} · {r.date}</div>
                        </div>
                        <div className="text-right shrink-0">
                            <div className="text-xs font-bold text-slate-800">¥{r.amount.toFixed(0)}</div>
                            <div className="text-[10px] text-rose-400">自付 ¥{r.self_pay.toFixed(0)}</div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// ─── 3. Payment Records Card (缴费记录) ──────────────────────────────────────
const InsurancePaymentsCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const records = (data.records as PaymentRecord[]) ?? [];
    const totalIndividual = (data.annual_total_individual as number) ?? 0;
    const totalEmployer = (data.annual_total_employer as number) ?? 0;

    return (
        <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            {/* Header */}
            <div className="bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-3 flex items-center justify-between">
                <div className="flex items-center gap-2 text-white">
                    <Calendar size={16} />
                    <span className="font-bold text-sm">医保缴费记录</span>
                </div>
                <span className="text-emerald-100 text-xs">近 {records.length} 个月</span>
            </div>

            {/* Totals */}
            <div className="grid grid-cols-2 divide-x divide-slate-100 border-b border-slate-100">
                <div className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 mb-0.5">个人累计</div>
                    <div className="font-black text-sm text-slate-800 tabular-nums">¥{totalIndividual.toFixed(0)}</div>
                </div>
                <div className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 mb-0.5">单位累计</div>
                    <div className="font-black text-sm text-emerald-600 tabular-nums">¥{totalEmployer.toFixed(0)}</div>
                </div>
            </div>

            {/* Records */}
            <div className="divide-y divide-slate-50">
                {records.map((r, i) => (
                    <div key={i} className="flex items-center px-4 py-2.5 gap-3">
                        <div className="w-8 h-8 bg-emerald-50 text-emerald-500 rounded-xl flex items-center justify-center shrink-0">
                            <Calendar size={13} />
                        </div>
                        <div className="flex-1">
                            <div className="text-xs font-bold text-slate-700">{r.year_month}</div>
                            <div className="text-[10px] text-slate-400">个人 ¥{r.individual} + 单位 ¥{r.employer}</div>
                        </div>
                        <div className="text-right">
                            <div className="text-xs font-black text-slate-800">¥{r.total.toFixed(0)}</div>
                            <span className="text-[10px] bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded font-bold">{r.status}</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// ─── 4. Cross-Region Card (异地就医) ─────────────────────────────────────────
const InsuranceCrossRegionCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const status = (data.status as string) ?? '未备案';
    const city = (data.city as string) ?? '';
    const province = (data.province as string) ?? '';
    const filedDate = (data.filed_date as string) ?? '';
    const validUntil = (data.valid_until as string) ?? '';
    const hospitals = (data.designated_hospitals as DesignatedHospital[]) ?? [];
    const reimRate = (data.reimbursement_rate as string) ?? '';
    const howTo = (data.how_to_use as string) ?? '';
    const isActive = status === '已备案';

    return (
        <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            {/* Header */}
            <div className={`px-4 py-3 flex items-center justify-between ${isActive
                ? 'bg-gradient-to-r from-violet-500 to-purple-500'
                : 'bg-gradient-to-r from-slate-400 to-slate-500'}`}>
                <div className="flex items-center gap-2 text-white">
                    <MapPin size={16} />
                    <span className="font-bold text-sm">异地就医备案</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${isActive
                    ? 'bg-white/25 text-white'
                    : 'bg-white/20 text-white/80'}`}>{status}</span>
            </div>

            <div className="p-4 space-y-3">
                {/* Location & dates */}
                {isActive && (
                    <div className="flex gap-2">
                        <div className="flex-1 bg-violet-50 rounded-xl p-3">
                            <div className="text-[10px] text-violet-400 mb-0.5">备案城市</div>
                            <div className="text-sm font-black text-violet-700">{city}</div>
                            <div className="text-[10px] text-violet-400">{province}</div>
                        </div>
                        <div className="flex-1 bg-slate-50 rounded-xl p-3">
                            <div className="text-[10px] text-slate-400 mb-0.5">有效期</div>
                            <div className="text-xs font-bold text-slate-700">{filedDate}</div>
                            <div className="flex items-center gap-1 text-[10px] text-slate-400">
                                <ArrowRight size={10} /> {validUntil}
                            </div>
                        </div>
                    </div>
                )}

                {/* Reimbursement rate */}
                {reimRate && (
                    <div className="bg-violet-50 border border-violet-100 rounded-xl p-3">
                        <div className="text-[10px] text-violet-400 mb-1 font-bold">报销比例</div>
                        <div className="text-xs text-violet-700 font-bold">{reimRate}</div>
                    </div>
                )}

                {/* Designated hospitals */}
                {hospitals.length > 0 && (
                    <div>
                        <div className="text-[10px] text-slate-400 font-bold mb-2">定点医院（部分）</div>
                        <div className="space-y-1.5">
                            {hospitals.map((h, i) => (
                                <div key={i} className="flex items-center justify-between bg-slate-50 rounded-xl px-3 py-2">
                                    <div className="flex items-center gap-2">
                                        <Building2 size={13} className="text-slate-400" />
                                        <span className="text-xs font-bold text-slate-700">{h.name}</span>
                                    </div>
                                    <div className="flex gap-1">
                                        <span className="text-[10px] bg-violet-100 text-violet-600 px-1.5 py-0.5 rounded font-bold">{h.level}</span>
                                        <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-bold">{h.type}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* How to use */}
                {howTo && (
                    <div className="text-[11px] text-slate-500 leading-relaxed bg-slate-50 rounded-xl p-3 border border-slate-100">
                        💡 {howTo}
                    </div>
                )}
            </div>
        </div>
    );
};

// ─── 5. Clinic Recommendation Card ──────────────────────────────────────────
const ClinicRecommendationCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const severityMap = { low: '可择期就诊', medium: '建议尽快就诊', high: '🚨 请立刻就诊' };
    const summary = (data.summary as string) ?? '根据您的描述，建议您就诊以下科室。';
    const departments = (data.departments as string[]) ?? [];
    const severity = (data.severity as 'low' | 'medium' | 'high') ?? 'low';
    return (
        <div className="bg-gradient-to-br from-teal-50 to-emerald-50 border border-teal-100 rounded-2xl p-5 relative overflow-hidden shadow-sm">
            <div className="absolute right-0 bottom-0 opacity-5 text-teal-500"><Stethoscope size={80} /></div>
            <h3 className="font-bold text-teal-800 flex items-center gap-2 mb-2 text-sm"><Stethoscope size={16} /> AI 预问诊分析完成</h3>
            <p className="text-sm text-teal-700 leading-relaxed mb-3">{summary}</p>
            {departments.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-3">
                    {departments.map(dept => <span key={dept} className="bg-teal-100 text-teal-700 text-xs px-2.5 py-1 rounded-lg font-bold">{dept}</span>)}
                </div>
            )}
            <div className={`text-xs font-bold px-2 py-1 rounded-md inline-block ${severity === 'high' ? 'bg-red-100 text-red-700' : severity === 'medium' ? 'bg-yellow-100 text-yellow-700' : 'bg-teal-100 text-teal-700'}`}>
                {severityMap[severity]}
            </div>
        </div>
    );
};

// ─── 6. Report Analysis Card ────────────────────────────────────────────────
const ReportAnalysisCard: FC<{ data: Record<string, unknown> }> = ({ data }) => (
    <div className="bg-white border border-slate-100 rounded-2xl p-4 flex gap-3 shadow-sm">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${data.isAbnormal ? 'bg-rose-50 text-rose-500' : 'bg-teal-50 text-teal-500'}`}>
            <FileText size={20} />
        </div>
        <div>
            <div className="font-bold text-slate-800 text-sm">{(data.title as string) ?? '检验报告'}</div>
            <div className="text-xs text-slate-500 mt-0.5">{(data.hospital as string) ?? ''}</div>
            <div className="flex gap-2 mt-2 items-center">
                <span className={`text-[11px] px-2 py-0.5 rounded-md font-bold ${data.isAbnormal ? 'bg-rose-100 text-rose-600' : 'bg-teal-100 text-teal-600'}`}>
                    {(data.status as string) ?? (data.isAbnormal ? '有异常项' : '结果正常')}
                </span>
                {data.date && <span className="text-[10px] text-slate-400">{data.date as string}</span>}
            </div>
        </div>
    </div>
);

// ─── Card Factory ────────────────────────────────────────────────────────────
const ChatCardRenderer: FC<{ payload: ChatCardPayload }> = ({ payload }) => {
    switch (payload.type) {
        case 'mode_welcome': return <ModeWelcomeCard payload={payload} />;
        case 'mode_exit': return <ModeExitCard payload={payload} />;
        case 'insurance_balance': return <InsuranceBalanceCard data={payload.data} />;
        case 'insurance_expenses': return <InsuranceExpensesCard data={payload.data} />;
        case 'insurance_payments': return <InsurancePaymentsCard data={payload.data} />;
        case 'insurance_cross_region': return <InsuranceCrossRegionCard data={payload.data} />;
        case 'clinic_recommendation': return <ClinicRecommendationCard data={payload.data} />;
        case 'report_analysis': return <ReportAnalysisCard data={payload.data} />;
        default: return null;
    }
};

export default ChatCardRenderer;
