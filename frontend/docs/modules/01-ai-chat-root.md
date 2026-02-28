# 01. AI Chat & Navigation Root Design Specification

## 1. Overview
This module acts as the persistent bottom navigation bar and primary chat interface for the application. It features an intelligent AI router that listens to user inputs (text or voice) and automatically directs them to the correct sub-module based on intent recognition, while offering context-aware quick suggestion chips.

## 2. Key Features
- **Persistent AI Input Bar**: A sticky bottom footer containing a text input field, microphone icon for voice dictation, and an expand ("+") menu for attachments.
- **Intent-Based Smart Routing**: Parses natural language inputs (e.g., "I need to see a doctor", "Check my balance") and automatically switches `currentScreen` to `services` or `insurance`.
- **Dynamic Suggestion Chips**: Horizontally scrollable chips providing quick-action templates to guide users.
- **Conversational Memory Timeline**: A scrolling log of messages between the user and the assistant, persisting across screen changes.

## 3. User Flows
- **Message Send Flow**: User types "挂什么科" (Which department) → Hits Enter → Message appended to history → AI intent engine matches "科" (Department) → Instantly triggers `currentScreen = 'services'` → Appends AI response "已为您跳转..." (Redirected) to history.
- **Auto-scroll Flow**: New message arrives → `chatEndRef` automatically scrolls the view to the latest message.

## 4. Data Dictionary (Types/Interfaces)

```typescript
// Shared Types for AI Chat
export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: number;
  actionPayload?: {
    type: 'NAVIGATION' | 'SUGGESTION_UPDATE';
    targetScreen?: string;
  };
}

export interface NavigationModule {
  id: string; // matches ScreenType
  name: string;
  iconName: string; // Lucide icon reference
}
```

## 5. Component Breakdown
- **`GlobalChatView`**: The main scrolling area displaying `ChatMessage` bubbles. Differentiates sent (teal, right) and received (white, left) messages.
- **`BottomNavigationPanel`**: The fixed footer. Encapsulates the module grid (6 icons) and the `SuggestionScroller`.
- **`InputBar`**: The specific UI component handling text states, Send button, and Mic toggle.

## 6. API / Mock Data Requirements
- Requires a mock function `simulateAIIntent(text: string): IntentMatch` that mimics an LLM routing response based on keyword matching (`text.includes("医保")`).
- Requires `SUGGESTIONS` array (e.g., `["帮我查一下医保余额", "最近总是失眠怎么办"]`).
