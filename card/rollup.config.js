import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';

export default {
  input: 'src/rover-card.ts',
  output: {
    file: 'dist/rover-card.js',
    format: 'es',
    sourcemap: true
  },
  plugins: [
    resolve(),
    typescript(),
    terser()
  ]
};
