// ESLint runs only eslint-plugin-vue template rules that oxlint cannot see.
// eslint-plugin-oxlint comes last and turns off everything oxlint covers.
import pluginVue from "eslint-plugin-vue";
import oxlint from "eslint-plugin-oxlint";
import tsParser from "@typescript-eslint/parser";

export default [
  { ignores: ["dist/**", "src/api/generated/**"] },
  ...pluginVue.configs["flat/recommended"],
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: {
        parser: tsParser,
      },
    },
  },
  ...oxlint.buildFromOxlintConfigFile("./.oxlintrc.json"),
];
