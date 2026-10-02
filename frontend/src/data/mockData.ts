import type { ChatMode, HabitGoal } from '../types';
import { Camera, CreditCard, Heart, Stethoscope, Pill } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export const USER_NAME = "王*虎";

// Map modules with their specific chat mode target
export const MODULES: { id: ChatMode; name: string; icon: LucideIcon }[] = [
    { id: 'clinic', name: 'AI诊室', icon: Stethoscope },
    { id: 'dashboard', name: '健康小目标', icon: Heart },
    { id: 'pharmacy', name: '药管家', icon: Pill },
    { id: 'insurance', name: '查医保', icon: CreditCard },
    { id: 'report', name: '拍报告', icon: Camera },
];

export const MOCK_HABITS: HabitGoal[] = [
    { title: '喝水 2000ml', current: '1200ml', progress: 60, tone: 'info' },
    { title: '户外步行', current: '8542步', progress: 85, tone: 'brand' },
    { title: '测血压', current: '未测量', progress: 0, tone: 'danger' }
];

