import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [
      vue(),
      // Element Plus 按需加载：模板组件与 ElMessage / ElMessageBox 均自动引入样式
      AutoImport({
        resolvers: [ElementPlusResolver()],
        dts: 'src/auto-imports.d.ts',
      }),
      Components({
        resolvers: [ElementPlusResolver()],
        dts: 'src/components.d.ts',
      }),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        // 开发环境把 /api 转发到 FastAPI，避免跨域并保持与生产同源路径一致
        '/api': {
          target:
            process.env.VITE_PROXY_TARGET || env.VITE_PROXY_TARGET || 'http://127.0.0.1:18080',
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
    },
    build: {
      rolldownOptions: {
        output: {
          // 图表与组件库独立成块，业务页面更新时可复用浏览器缓存
          codeSplitting: {
            groups: [
              { name: 'zrender', test: /node_modules[\\/]zrender/ },
              { name: 'echarts', test: /node_modules[\\/]echarts/ },
              { name: 'element-plus', test: /node_modules[\\/]element-plus/ },
            ],
          },
        },
      },
    },
  }
})
