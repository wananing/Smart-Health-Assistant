import { useState } from 'react';
import type { FC } from 'react';
import {
    Stethoscope, ShieldCheck, Eye, EyeOff, ScanLine, FileText, Receipt, CalendarCheck,
    MapPin, Building2, ArrowRight, ClipboardList, Pill, Store, Phone, Info, AlertTriangle,
    ArrowUp, ArrowDown,
} from 'lucide-react';
import type { ChatCardPayload, ClinicSummaryData } from '../../types';
import { ModeWelcomeCard, ModeExitCard } from './ModeContextCards';
import SensitiveImagePreview from '../common/SensitiveImagePreview';
import { Badge, Note, ResultCard, SectionLabel, Stat } from '../common/ResultCard';
import type { Tone } from '../common/ResultCard';
import { useTextScale } from '../../design/textScale';

// ─── shared sub-types ───────────────────────────────────────────────────────
interface InsuranceUser { name?: string; region?: string; insurance_type?: string; }

interface ExpenseRecord {
    date: string; hospital: string; department: string;
    amount: number; self_pay: number; reimbursed: number; category: string;
}
interface PaymentRecord {
    year_month: string; individual: number; employer: number; total: number; status: string;
}
interface DesignatedHospital { name: string; level: string; type: string; }

interface DrugInfo {
    generic_name?: string; brand_names?: string[]; category?: string; indications?: string[];
    dosage?: string; contraindications?: string[]; warnings?: string[]; price_range?: string; otc?: boolean;
}
interface PharmacyRecord {
    name: string; distance: string; hours: string; phone: string; type: string; supports_insurance: boolean;
}
interface LabFinding {
    name: string; full_name?: string; value: number; unit?: string;
    status: 'HIGH' | 'LOW' | 'NORMAL' | 'UNKNOWN'; reference?: string; clinical_note?: string;
}

const yuan = (value: number, digits = 0) =>
    `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

// ─── 1. Insurance Balance Card ───────────────────────────────────────────────
// The one "credential" card: a brand-coloured face like the physical insurance card.
const InsuranceBalanceCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const [showBalance, setShowBalance] = useState(true);
    const user = data.user as InsuranceUser | undefined;
    const personalAccount = (data.personal_account as number) ?? 2458.32;
    const medicalSavings = (data.medical_savings as number) ?? 12800.00;
    const lastDeposit = (data.last_month_deposit as number) ?? 320.00;
    const updatedAt = (data.updated_at as string) ?? '';
    const masked = (text: string) => (showBalance ? text : '****');

    return (
        <section className="relative overflow-hidden rounded-card bg-gradient-to-br from-brand-700 to-brand-900 p-5 text-white shadow-raised font-cn animate-rise motion-reduce:animate-none">
            <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10" />
            <div className="pointer-events-none absolute -right-4 top-16 h-24 w-24 rounded-full bg-white/5" />
            <div className={`relative flex items-center gap-1.5 text-brand-100 ${t.caption}`}>
                <ShieldCheck size={14} /> 国家医保电子凭证
                {updatedAt && <span className="ml-auto tabular-nums">更新于 {updatedAt}</span>}
            </div>
            <div className={`relative mt-0.5 font-semibold ${t.callout}`}>
                {user?.region ?? '北京市'} · {user?.insurance_type ?? '城镇职工医保'}
            </div>

            <div className="relative mt-4 flex items-end justify-between gap-3">
                <div className="min-w-0">
                    <div className={`flex items-center gap-2 text-brand-100 ${t.caption}`}>
                        个人账户余额（元）
                        <button
                            onClick={() => setShowBalance(v => !v)}
                            aria-label={showBalance ? '隐藏金额' : '显示金额'}
                            className="rounded-full p-1 -m-1 hover:text-white transition-colors duration-base"
                        >
                            {showBalance ? <Eye size={16} /> : <EyeOff size={16} />}
                        </button>
                    </div>
                    <div className="mt-1 text-display font-semibold tabular-nums">
                        {showBalance ? personalAccount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) : '****.**'}
                    </div>
                </div>
                <button className={`shrink-0 flex flex-col items-center gap-1 rounded-control bg-white/15 px-3 py-2 font-semibold ring-1 ring-inset ring-white/25 hover:bg-white/25 active:scale-[0.97] transition duration-fast ${t.caption}`}>
                    <ScanLine size={20} />
                    去支付
                </button>
            </div>

            <div className="relative mt-4 grid grid-cols-2 gap-2">
                {[
                    ['统筹可用', masked(yuan(medicalSavings))],
                    ['上月入账', yuan(lastDeposit, 2)],
                ].map(([label, value]) => (
                    <div key={label} className="min-w-0 rounded-control bg-white/10 px-3 py-2">
                        <div className={`text-brand-100 ${t.caption}`}>{label}</div>
                        <div className={`font-semibold tabular-nums truncate ${t.body}`}>{value}</div>
                    </div>
                ))}
            </div>
        </section>
    );
};

// ─── 2. Expenses Card (消费明细) ─────────────────────────────────────────────
const InsuranceExpensesCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const records = (data.records as ExpenseRecord[]) ?? [];
    const totalAmt = (data.total_amount as number) ?? 0;
    const totalSelf = (data.total_self_pay as number) ?? 0;
    const totalReimb = (data.total_reimbursed as number) ?? 0;
    const reimbRate = totalAmt > 0 ? Math.round((totalReimb / totalAmt) * 100) : 0;

    return (
        <ResultCard
            icon={Receipt}
            title="医保消费明细"
            meta={<span className={`text-ink-600 ${t.caption}`}>近 {(data.period_months as number) ?? 3} 个月</span>}
        >
            <div className="grid grid-cols-3 gap-2">
                <Stat label="总费用" value={yuan(totalAmt)} />
                <Stat label="自付" value={yuan(totalSelf)} />
                <Stat label="报销率" value={`${reimbRate}%`} tone="success" />
            </div>
            {records.length > 0 && (
                <ul className="divide-y divide-ink-100 max-h-64 overflow-y-auto overscroll-contain -mx-1 px-1">
                    {records.map((r, i) => (
                        <li key={i} className="flex items-center gap-3 py-2.5">
                            <span className="w-9 h-9 rounded-full bg-ink-100 text-ink-600 flex items-center justify-center shrink-0">
                                <Building2 size={16} />
                            </span>
                            <div className="flex-1 min-w-0">
                                <div className={`font-semibold text-ink-900 truncate ${t.body}`}>{r.hospital}</div>
                                <div className={`text-ink-600 truncate ${t.caption}`}>{r.department} · {r.date}</div>
                            </div>
                            <div className="text-right shrink-0">
                                <div className={`font-semibold text-ink-900 tabular-nums ${t.body}`}>{yuan(r.amount)}</div>
                                <div className={`text-ink-600 tabular-nums ${t.caption}`}>自付 {yuan(r.self_pay)}</div>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </ResultCard>
    );
};

// ─── 3. Payment Records Card (缴费记录) ──────────────────────────────────────
const InsurancePaymentsCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const records = (data.records as PaymentRecord[]) ?? [];
    const totalIndividual = (data.annual_total_individual as number) ?? 0;
    const totalEmployer = (data.annual_total_employer as number) ?? 0;

    return (
        <ResultCard
            icon={CalendarCheck}
            title="医保缴费记录"
            meta={<span className={`text-ink-600 ${t.caption}`}>近 {records.length} 个月</span>}
        >
            <div className="grid grid-cols-2 gap-2">
                <Stat label="个人累计" value={yuan(totalIndividual)} />
                <Stat label="单位累计" value={yuan(totalEmployer)} />
            </div>
            {records.length > 0 && (
                <ul className="divide-y divide-ink-100">
                    {records.map((r, i) => (
                        <li key={i} className="flex items-center gap-3 py-2.5">
                            <div className="flex-1 min-w-0">
                                <div className={`font-semibold text-ink-900 tabular-nums ${t.body}`}>{r.year_month}</div>
                                <div className={`text-ink-600 tabular-nums truncate ${t.caption}`}>个人 {yuan(r.individual)} + 单位 {yuan(r.employer)}</div>
                            </div>
                            <div className={`font-semibold text-ink-900 tabular-nums ${t.body}`}>{yuan(r.total)}</div>
                            <Badge tone={r.status === '已入账' || r.status === '已缴费' ? 'success' : 'neutral'}>{r.status}</Badge>
                        </li>
                    ))}
                </ul>
            )}
        </ResultCard>
    );
};

// ─── 4. Cross-Region Card (异地就医) ─────────────────────────────────────────
const InsuranceCrossRegionCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
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
        <ResultCard icon={MapPin} title="异地就医备案" meta={<Badge tone={isActive ? 'success' : 'neutral'}>{status}</Badge>}>
            {isActive && (
                <div className="grid grid-cols-2 gap-2">
                    <Stat label="备案城市" value={city} sub={province} />
                    <Stat
                        label="有效期"
                        value={<span className={t.body}>{filedDate}</span>}
                        sub={<span className="inline-flex items-center gap-1"><ArrowRight size={12} /> {validUntil}</span>}
                    />
                </div>
            )}

            {reimRate && (
                <div className="rounded-control bg-brand-50 px-3 py-2.5">
                    <div className={`text-brand-800 ${t.caption}`}>报销比例</div>
                    <div className={`font-semibold text-brand-900 ${t.body}`}>{reimRate}</div>
                </div>
            )}

            {hospitals.length > 0 && (
                <div>
                    <SectionLabel>定点医院（部分）</SectionLabel>
                    <ul className="divide-y divide-ink-100">
                        {hospitals.map((h, i) => (
                            <li key={i} className="flex items-center gap-2 py-2">
                                <Building2 size={15} className="text-ink-500 shrink-0" />
                                <span className={`flex-1 min-w-0 truncate font-semibold text-ink-900 ${t.body}`}>{h.name}</span>
                                <Badge tone="brand">{h.level}</Badge>
                                <Badge>{h.type}</Badge>
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {howTo && <Note icon={Info}>{howTo}</Note>}
        </ResultCard>
    );
};

// ─── 5. Clinic Recommendation Card ──────────────────────────────────────────
type Urgency = 'emergency' | 'soon' | 'routine';

const URGENCY_META: Record<Urgency, { label: string; tone: Tone }> = {
    emergency: { label: '请立即就医', tone: 'danger' },
    soon: { label: '建议尽快就诊', tone: 'warning' },
    routine: { label: '可择期就诊', tone: 'brand' },
};

const SEVERITY_TO_URGENCY: Record<string, Urgency> = { high: 'emergency', medium: 'soon', low: 'routine' };

const ClinicRecommendationCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const summary = (data.summary as string) ?? '根据您的描述，建议您就诊以下科室。';
    const departments = (data.departments as string[]) ?? [];
    const notes = ((data.notes as string[]) ?? []).filter(Boolean);
    const urgency: Urgency = (data.urgency as Urgency) ?? SEVERITY_TO_URGENCY[(data.severity as string) ?? 'low'] ?? 'routine';
    const meta = URGENCY_META[urgency] ?? URGENCY_META.routine;
    const isEmergency = urgency === 'emergency';

    return (
        <ResultCard
            icon={isEmergency ? AlertTriangle : Stethoscope}
            tone={isEmergency ? 'danger' : 'brand'}
            alert={isEmergency}
            title="分诊建议"
            meta={<Badge tone={meta.tone}>{meta.label}</Badge>}
            dataCard="clinic_recommendation"
        >
            <p className={`text-ink-800 ${t.callout}`}>{summary}</p>
            {departments.length > 0 && (
                <div>
                    <SectionLabel>推荐科室</SectionLabel>
                    <div className="flex flex-wrap gap-2">
                        {departments.map(dept => (
                            <span key={dept} className={`rounded-full bg-brand-700 px-3 py-1 font-semibold text-white ${t.body}`}>{dept}</span>
                        ))}
                    </div>
                </div>
            )}
            {notes.length > 0 && (
                <div>
                    <SectionLabel>就诊前注意</SectionLabel>
                    <ul className={`list-disc pl-5 space-y-0.5 text-ink-700 marker:text-ink-400 ${t.body}`}>
                        {notes.map((note, idx) => <li key={idx}>{note}</li>)}
                    </ul>
                </div>
            )}
            <p className={`text-ink-500 ${t.caption}`}>AI 预问诊结果仅供参考，不能代替医生诊断。</p>
        </ResultCard>
    );
};

// ─── 6. Report Analysis Card ────────────────────────────────────────────────
const FINDING_META: Record<LabFinding['status'], { label: string; tone: Tone; icon?: typeof ArrowUp }> = {
    HIGH: { label: '偏高', tone: 'warning', icon: ArrowUp },
    LOW: { label: '偏低', tone: 'warning', icon: ArrowDown },
    NORMAL: { label: '正常', tone: 'success' },
    UNKNOWN: { label: '无参考', tone: 'neutral' },
};

const ReportAnalysisCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const findings = (data.findings as LabFinding[]) ?? [];
    const abnormalCount = Number(data.abnormal_count ?? findings.filter(f => f.status === 'HIGH' || f.status === 'LOW').length);
    const isAbnormal = Boolean(data.isAbnormal ?? abnormalCount > 0);
    const statusText = (data.status as string) ?? (isAbnormal ? `${abnormalCount} 项异常` : '结果正常');
    const summary = data.summary as string | undefined;
    const date = data.date as string | undefined;
    const hospital = data.hospital as string | undefined;
    const disclaimer = data.disclaimer as string | undefined;
    // Abnormal items first; normal ones keep their original order after them.
    const ordered = [...findings].sort((a, b) => Number(b.status === 'HIGH' || b.status === 'LOW') - Number(a.status === 'HIGH' || a.status === 'LOW'));

    return (
        <ResultCard
            icon={FileText}
            tone={isAbnormal ? 'warning' : 'brand'}
            title={(data.title as string) ?? '检验报告解读'}
            meta={<Badge tone={isAbnormal ? 'warning' : 'success'}>{statusText}</Badge>}
        >
            {(hospital || date) && (
                <div className={`-mt-2 text-ink-600 ${t.caption}`}>{[hospital, date].filter(Boolean).join(' · ')}</div>
            )}
            {summary && <p className={`text-ink-800 ${t.body}`}>{summary}</p>}
            {ordered.length > 0 && (
                <ul className="divide-y divide-ink-100">
                    {ordered.map((f, i) => {
                        const meta = FINDING_META[f.status] ?? FINDING_META.UNKNOWN;
                        const abnormal = f.status === 'HIGH' || f.status === 'LOW';
                        const Arrow = meta.icon;
                        return (
                            <li key={`${f.name}-${i}`} className="py-2.5">
                                <div className="flex items-center gap-3">
                                    <div className="flex-1 min-w-0">
                                        <div className={`font-semibold text-ink-900 ${t.body}`}>
                                            {f.full_name || f.name}
                                            {f.full_name && f.full_name !== f.name && <span className="font-normal text-ink-500"> {f.name}</span>}
                                        </div>
                                        {f.reference && <div className={`text-ink-600 ${t.caption}`}>参考 {f.reference}</div>}
                                    </div>
                                    <div className={`font-semibold tabular-nums ${abnormal ? 'text-warning-700' : 'text-ink-900'} ${t.body}`}>
                                        {f.value}{f.unit && <span className={`font-normal text-ink-500 ${t.caption}`}> {f.unit}</span>}
                                    </div>
                                    <Badge tone={meta.tone}>{Arrow && <Arrow size={12} />}{meta.label}</Badge>
                                </div>
                                {abnormal && f.clinical_note && <p className={`mt-1 text-ink-700 ${t.caption}`}>{f.clinical_note}</p>}
                            </li>
                        );
                    })}
                </ul>
            )}
            {disclaimer && <p className={`text-ink-500 ${t.caption}`}>{disclaimer}</p>}
        </ResultCard>
    );
};

// ─── 7. Medication Card (药品信息) ───────────────────────────────────────────
const MedicationCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const query = (data.query as string) ?? '';
    const drug = data.drug as DrugInfo | undefined;

    if (!data.found || !drug) {
        return (
            <ResultCard icon={Pill} tone="neutral" title={query || '药品查询'} meta={<Badge>未收录</Badge>}>
                <Note icon={Info}>药品库里暂未收录「{query}」，回答中已结合医学知识库说明。用药前请咨询药师或医生。</Note>
            </ResultCard>
        );
    }

    const brands = drug.brand_names?.filter(Boolean) ?? [];
    return (
        <ResultCard
            icon={Pill}
            title={drug.generic_name || query}
            meta={<Badge tone={drug.otc ? 'success' : 'warning'}>{drug.otc ? '非处方药' : '处方药'}</Badge>}
        >
            {(brands.length > 0 || drug.category) && (
                <div className={`-mt-2 text-ink-600 ${t.caption}`}>
                    {[drug.category, brands.length > 0 ? `商品名：${brands.join('、')}` : ''].filter(Boolean).join(' · ')}
                </div>
            )}
            {drug.indications && drug.indications.length > 0 && (
                <div>
                    <SectionLabel>适应症</SectionLabel>
                    <div className="flex flex-wrap gap-1.5">
                        {drug.indications.map(item => <Badge key={item} tone="brand">{item}</Badge>)}
                    </div>
                </div>
            )}
            {drug.dosage && (
                <div>
                    <SectionLabel>用法用量</SectionLabel>
                    <p className={`text-ink-800 ${t.body}`}>{drug.dosage}</p>
                </div>
            )}
            {drug.warnings && drug.warnings.length > 0 && (
                <div className="rounded-control bg-warning-50 px-3 py-2.5">
                    <div className={`mb-1 flex items-center gap-1.5 font-semibold text-warning-800 ${t.caption}`}>
                        <AlertTriangle size={14} /> 注意事项
                    </div>
                    <ul className={`list-disc pl-5 space-y-0.5 text-ink-800 marker:text-warning-500 ${t.body}`}>
                        {drug.warnings.map(item => <li key={item}>{item}</li>)}
                    </ul>
                </div>
            )}
            {drug.contraindications && drug.contraindications.length > 0 && (
                <div>
                    <SectionLabel>禁忌</SectionLabel>
                    <ul className={`list-disc pl-5 space-y-0.5 text-ink-700 marker:text-ink-400 ${t.body}`}>
                        {drug.contraindications.map(item => <li key={item}>{item}</li>)}
                    </ul>
                </div>
            )}
            {drug.price_range && <div className={`text-ink-600 ${t.caption}`}>参考价格 {drug.price_range}</div>}
        </ResultCard>
    );
};

// ─── 8. Nearby Pharmacies Card (附近药店) ────────────────────────────────────
const PharmacyListCard: FC<{ data: Record<string, unknown> }> = ({ data }) => {
    const t = useTextScale();
    const pharmacies = (data.pharmacies as PharmacyRecord[]) ?? [];
    const location = (data.location as string) ?? '';
    const tip = data.tip as string | undefined;

    return (
        <ResultCard icon={Store} title="附近药店" meta={location ? <span className={`text-ink-600 ${t.caption}`}>{location}</span> : undefined}>
            <ul className="divide-y divide-ink-100">
                {pharmacies.map((p, i) => {
                    const dialable = /\d/.test(p.phone);
                    return (
                        <li key={`${p.name}-${i}`} className="flex items-center gap-3 py-2.5">
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5 min-w-0">
                                    <span className={`font-semibold text-ink-900 truncate ${t.body}`}>{p.name}</span>
                                    {p.supports_insurance && <Badge tone="success">医保</Badge>}
                                </div>
                                <div className={`text-ink-600 truncate ${t.caption}`}>{p.type} · {p.hours}</div>
                            </div>
                            <div className={`shrink-0 font-semibold text-ink-900 tabular-nums ${t.body}`}>{p.distance}</div>
                            {dialable && (
                                <a
                                    href={`tel:${p.phone.replace(/[^\d+]/g, '')}`}
                                    aria-label={`拨打${p.name}电话`}
                                    className="shrink-0 w-9 h-9 rounded-full bg-brand-50 text-brand-700 flex items-center justify-center hover:bg-brand-100 active:scale-[0.94] transition duration-fast"
                                >
                                    <Phone size={16} />
                                </a>
                            )}
                        </li>
                    );
                })}
            </ul>
            {tip && <Note icon={Info}>{tip}</Note>}
        </ResultCard>
    );
};

// ─── 9. Clinic Summary Card (语音问诊小结) ────────────────────────────────────
const formatClock = (value?: string) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const formatDuration = (seconds?: number) => {
    if (seconds === undefined || seconds === null || !Number.isFinite(seconds)) return '';
    const s = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(s / 60);
    return minutes > 0 ? `${minutes} 分 ${s % 60} 秒` : `${s} 秒`;
};

const ClinicSummaryCard: FC<{ data: ClinicSummaryData }> = ({ data }) => {
    const t = useTextScale();
    const completed = data.status === 'completed';
    // The chief complaint has its own row; the backend also lists it among the facts.
    const facts = (data.facts ?? []).filter(fact => fact.value && fact.field !== 'chief_complaint');
    const chiefComplaint = data.chief_complaint
        || data.facts?.find(fact => fact.field === 'chief_complaint')?.value
        || '';
    const departments = data.departments ?? [];
    const notes = data.notes?.filter(Boolean) ?? [];
    const flags = data.emergency_flags?.filter(Boolean) ?? [];
    const urgency = data.urgency ? URGENCY_META[data.urgency] : null;
    const duration = formatDuration(data.duration_seconds);

    return (
        <ResultCard
            icon={ClipboardList}
            title="语音问诊小结"
            alert={flags.length > 0}
            meta={<Badge tone={completed ? 'success' : 'warning'}>{completed ? '已完成' : '未完成'}</Badge>}
            dataCard="clinic_summary"
        >
            <div className={`-mt-2 flex flex-wrap justify-between gap-x-3 text-ink-600 ${t.caption}`}>
                <span>咨询人：{data.consultant || '—'}</span>
                <span>
                    {formatClock(data.ended_at || data.started_at)}
                    {duration && <> · 通话时长 {duration}</>}
                </span>
            </div>

            {flags.length > 0 && (
                <div className="rounded-control bg-danger-50 px-3 py-2.5">
                    <div className={`mb-1.5 flex items-center gap-1.5 font-semibold text-danger-700 ${t.caption}`}>
                        <AlertTriangle size={14} /> 通话中识别到的危险信号
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                        {flags.map(flag => <Badge key={flag} tone="danger">{flag}</Badge>)}
                    </div>
                </div>
            )}

            {chiefComplaint && (
                <div>
                    <SectionLabel>主诉</SectionLabel>
                    <div className={`font-semibold text-ink-900 ${t.callout}`}>{chiefComplaint}</div>
                </div>
            )}

            {facts.length > 0 && (
                <dl className="grid grid-cols-2 gap-2">
                    {facts.map(fact => (
                        <div key={fact.field} className="min-w-0 rounded-control bg-ink-50 px-3 py-2">
                            <dt className={`text-ink-600 ${t.caption}`}>{fact.label}</dt>
                            <dd className={`font-semibold text-ink-900 ${t.body}`}>{fact.value}</dd>
                        </div>
                    ))}
                </dl>
            )}

            {!completed && (
                <Note icon={Info}>通话在给出建议前结束，以上只是已收集的要点。可以继续用文字补充。</Note>
            )}

            {data.summary && <p className={`text-ink-800 ${t.callout}`}>{data.summary}</p>}

            {(departments.length > 0 || urgency) && (
                <div className="flex flex-wrap gap-2 items-center">
                    {departments.map(dept => (
                        <span key={dept} className={`rounded-full bg-brand-700 px-3 py-1 font-semibold text-white ${t.body}`}>{dept}</span>
                    ))}
                    {urgency && <Badge tone={urgency.tone}>{urgency.label}</Badge>}
                </div>
            )}

            {notes.length > 0 && (
                <ul className={`list-disc pl-5 space-y-0.5 text-ink-700 marker:text-ink-400 ${t.body}`}>
                    {notes.map((note, idx) => <li key={idx}>{note}</li>)}
                </ul>
            )}

            <p className={`border-t border-ink-100 pt-2.5 text-ink-500 ${t.caption}`}>
                {data.disclaimer || 'AI 预问诊结果仅供参考，不构成医疗诊断。'}
            </p>
        </ResultCard>
    );
};

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
        case 'clinic_summary': return <ClinicSummaryCard data={payload.data} />;
        case 'report_analysis': return <ReportAnalysisCard data={payload.data} />;
        case 'medication_task': return <MedicationCard data={payload.data} />;
        case 'hospital_list': return <PharmacyListCard data={payload.data} />;
        case 'sensitive_image_preview': return <SensitiveImagePreview {...payload.data} />;
        default: return null;
    }
};

export default ChatCardRenderer;
