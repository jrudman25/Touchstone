import { createApp, watch } from "vue";
import { createPinia } from "pinia";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";

import App from "./App.vue";
import { createAppRouter } from "./router";
import { useAuthStore } from "./stores/auth";
import "./style.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
});

const app = createApp(App);
app.use(createPinia());

const router = createAppRouter();
app.use(router);
app.use(VueQueryPlugin, { queryClient });

const auth = useAuthStore();
watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      return;
    }
    queryClient.clear();
    if (router.currentRoute.value.meta.public !== true) {
      void router.replace({ name: "login" });
    }
  },
);

app.mount("#app");
