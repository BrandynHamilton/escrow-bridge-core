import Head from "next/head";
import SettlementInitForm from "@/components/SettlementInitForm";

export default function Home() {
  return (
    <>
      <Head>
        <title>Settlement UI</title>
      </Head>
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <SettlementInitForm />
      </main>
    </>
  );
}
