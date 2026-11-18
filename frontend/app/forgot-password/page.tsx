"use client";

import { useRouter } from "next/navigation";
import { ForgotPasswordView } from "@/components/auth/forgot-password-view";

export default function ForgotPasswordPage() {
  const router = useRouter();

  return (
    <ForgotPasswordView
      onNavigateLogin={() => router.push("/")}
    />
  );
}
