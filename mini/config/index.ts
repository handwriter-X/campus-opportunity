import { defineConfig } from '@tarojs/cli'
import path from 'path'

export default defineConfig({
  projectName: 'opportunity-pool-mini',
  date: '2026-4-1',
  designWidth: 750,
  deviceRatio: {
    640: 2.34 / 2,
    750: 1,
    828: 1.81 / 2
  },
  sourceRoot: 'src',
  outputRoot: 'dist',
  plugins: [],
  defineConstants: {},
  copy: {
    patterns: [],
    options: {}
  },
  framework: 'react',
  compiler: 'webpack5',
  cache: {
    enable: false
  },
  mini: {
    postcss: {
      pxtransform: {
        enable: true,
        config: {}
      },
      url: {
        enable: true,
        config: {
          limit: 10240
        }
      }
    },
    webpackChain(chain) {
      // 1. 设置路径别名
      chain.resolve.alias.set('@', path.resolve(__dirname, '..', 'src'))
      // 2. 关闭 eval
      chain.devtool(false)

      // 3. 终极根治 _raf 的 Temporal Dead Zone 报错：将所有 let/const _raf 转换为 var _raf
      chain.plugin('fix-raf-tdz-plugin').use({
        apply(compiler: any) {
          compiler.hooks.emit.tap('FixRafTdzPlugin', (compilation: any) => {
            for (const filename in compilation.assets) {
              if (filename.endsWith('.js')) {
                let asset = compilation.assets[filename];
                let content = asset.source();
                if (content.includes('_raf')) {
                  let newContent = content
                    .replace(/\blet\s+_raf\b/g, 'var _raf')
                    .replace(/\bconst\s+_raf\b/g, 'var _raf');
                  compilation.assets[filename] = {
                    source: () => newContent,
                    size: () => newContent.length
                  };
                }
              }
            }
          });
        }
      })
    }
  },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    postcss: {
      autoprefixer: {
        enable: true,
        config: {}
      },
      cssModules: {
        enable: false,
        config: {
          namingPattern: 'module',
          generateScopedName: '[name]__[local]___[hash:base64:5]'
        }
      }
    }
  }
})