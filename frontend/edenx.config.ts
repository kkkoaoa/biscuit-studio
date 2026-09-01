import { appTools, defineConfig } from '@edenx/app-tools';
import { CodeInspectorPlugin } from '@rdservices/aime-code-inspector';

// https://edenx.bytedance.net/configure/app/usage
export default defineConfig({
  devtools: false,
  plugins: [appTools()],
  tools: {
    rspack: (config) => {
      config.plugins?.push(CodeInspectorPlugin({ bundler: 'rspack' }));
    },
  },
});
