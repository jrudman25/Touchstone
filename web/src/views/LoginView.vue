<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { safeRedirect } from "../router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const username = ref("");
const password = ref("");
const pending = ref(false);
const errorMessage = ref<string | null>(null);

async function submit() {
  pending.value = true;
  errorMessage.value = null;
  try {
    await auth.login(username.value, password.value);
    await router.push(safeRedirect(route.query.redirect) ?? { name: "home" });
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Sign in failed. Try again.";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <form
      class="card"
      @submit.prevent="submit"
    >
      <h1>Touchstone</h1>
      <p class="muted">
        Sign in to continue
      </p>

      <div class="field">
        <label for="username">Username</label>
        <input
          id="username"
          v-model="username"
          name="username"
          type="text"
          autocomplete="username"
          required
        >
      </div>

      <div class="field">
        <label for="password">Password</label>
        <input
          id="password"
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
        >
      </div>

      <p
        v-if="errorMessage"
        role="alert"
        class="error"
      >
        {{ errorMessage }}
      </p>

      <button
        type="submit"
        :disabled="pending"
      >
        {{ pending ? "Signing in..." : "Sign in" }}
      </button>
    </form>
  </main>
</template>
