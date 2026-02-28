import type { FC } from 'react';
import { Search } from 'lucide-react';

const SearchHeader: FC = () => {
    return (
        <div className="bg-gradient-to-r from-blue-500 to-indigo-500 rounded-3xl p-6 text-white mb-6 shadow-lg shadow-blue-100">
            <h3 className="font-bold text-xl mb-2">智能导诊与挂号</h3>
            <p className="text-blue-100 text-xs mb-5 font-medium">直连全国 3000+ 三甲公立医院号源</p>
            <div className="relative shadow-sm rounded-xl">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-blue-500" size={20} />
                <input type="text" placeholder="搜索医院、科室、医生..." className="w-full bg-white text-slate-800 font-bold rounded-xl py-4 pl-12 pr-4 text-sm focus:outline-none focus:ring-4 focus:ring-blue-300 transition-all placeholder-slate-400" />
            </div>
        </div>
    );
};

export default SearchHeader;
