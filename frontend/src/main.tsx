import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import Page from '@/routes/page';
import '@/routes/index.css';

const root = document.getElementById('root');

if (!root) {
  throw new Error('Root element not found');
}

createRoot(root).render(
  <StrictMode>
    <Page />
  </StrictMode>,
);
