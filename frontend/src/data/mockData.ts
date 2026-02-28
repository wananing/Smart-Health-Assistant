import { Camera, CreditCard, Heart, Activity, Stethoscope, Pill, History, User, Zap } from 'lucide-react';

export const SYSTEM_NAME = "大健康 AI";
export const USER_NAME = "王*虎";

// Map modules with their specific chat mode target
export const MODULES: { id: string; name: string; icon: React.FC<any> }[] = [
    { id: 'clinic', name: 'AI诊室', icon: Stethoscope },
    { id: 'dashboard', name: '健康小目标', icon: Heart },
    { id: 'pharmacy', name: '药管家', icon: Pill },
    { id: 'insurance', name: '查医保', icon: CreditCard },
    { id: 'report', name: '拍报告', icon: Camera },
    { id: 'services', name: '就医服务', icon: Activity },
];

export const SUGGESTIONS = [
    "想开点中药调理身体挂什么科？",
    "我最近总是失眠怎么办？",
    "帮我查一下医保余额",
    "扫码查一下这个感冒药真伪"
];

// Mock Data for specific screens
export const MOCK_HOSPITALS = [
    { name: '北京协和医院', tags: ['三级甲等', '综合'], distance: '3.2km', isAd: false },
    { name: '北京大学第三医院', tags: ['三级甲等', '运动医学'], distance: '5.1km', isAd: false },
    { name: '慈铭体检中心 (中关村店)', tags: ['专业体检'], distance: '1.2km', isAd: true },
];

export const MOCK_REPORTS = [
    { title: '血常规化验单', date: '2023-10-15', hospital: '北京协和医院', status: 'AI已解读', isAbnormal: true },
    { title: '甲状腺彩超报告', date: '2023-05-22', hospital: '北京大学第三医院', status: '正常', isAbnormal: false },
];

export const MOCK_HABITS = [
    { title: '喝水 2000ml', current: '1200ml', progress: 60, color: 'bg-blue-400' },
    { title: '户外步行', current: '8542步', progress: 85, color: 'bg-teal-500' },
    { title: '测血压', current: '未测量', progress: 0, color: 'bg-rose-400' }
];

export const MOCK_INSURANCE_SERVICES = [
    { label: '消费记录', sub: '近一月支出 ¥128.0', icon: History, color: 'text-teal-500', bg: 'bg-teal-50' },
    { label: '年度缴费', sub: '2024年已按时缴纳', icon: CreditCard, color: 'text-blue-500', bg: 'bg-blue-50' },
    { label: '共济管理', sub: '已绑定 2 位家人', icon: User, color: 'text-indigo-500', bg: 'bg-indigo-50' },
    { label: '异地备案', sub: '快捷跨省就医', icon: Zap, color: 'text-orange-500', bg: 'bg-orange-50' },
];
