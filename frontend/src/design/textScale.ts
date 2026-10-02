import { useGlobalStore } from '../store/GlobalContext';

/** Text-size classes by role; elder mode moves every role one step up. */
export interface TextScale {
    caption: string;
    body: string;
    callout: string;
    title: string;
    headline: string;
}

const STANDARD: TextScale = {
    caption: 'text-caption',
    body: 'text-body',
    callout: 'text-callout',
    title: 'text-title',
    headline: 'text-headline',
};

const ELDER: TextScale = {
    caption: 'text-body',
    body: 'text-callout',
    callout: 'text-title',
    title: 'text-headline',
    headline: 'text-display',
};

export const useTextScale = (): TextScale => {
    const { isElderMode } = useGlobalStore();
    return isElderMode ? ELDER : STANDARD;
};
