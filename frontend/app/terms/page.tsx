import type { Metadata } from "next";
import { LegalPageLayout, LegalSection } from "@/components/legal/legal-page-layout";

export const metadata: Metadata = {
  title: "Terms of Use | ClassMate AI",
  description: "Terms for using ClassMate AI's student assignment and Classroom tools.",
};

export default function TermsPage() {
  return (
    <LegalPageLayout
      title="Terms of Use"
      summary="These terms describe the current ClassMate AI features and the responsibilities involved in using them. Read them together with the Privacy Policy before creating an account."
    >
      <LegalSection title="1. Introduction and acceptance">
        <p>
          These Terms apply when you access or use the ClassMate AI website and
          services. Registration requires an affirmative agreement to this version
          and acknowledgment of the Privacy Policy. The application records the
          document versions and server-side acceptance time.
        </p>
        <p>
          ClassMate AI is not represented as sponsored, approved, or endorsed by
          Abbottabad University of Science &amp; Technology (AUST), Google, or any
          other institution. Follow your university&apos;s and instructor&apos;s own
          rules.
        </p>
      </LegalSection>

      <LegalSection title="2. Description of the service">
        <p>
          ClassMate AI can connect to a student&apos;s Google Classroom account,
          synchronize course and assignment information, store and organize drafts,
          provide AI writing suggestions, produce downloadable documents, and
          prepare an explicitly approved student submission. Availability depends
          on configuration, licensing, Google, and other service providers.
        </p>
      </LegalSection>

      <LegalSection title="3. Student account responsibilities">
        <p>
          Give accurate account information, protect your password and signed-in
          devices, and promptly revoke sessions you no longer control. A student
          account can have no more than two active registered browser devices.
          Separate browser profiles may count separately. Administrators are not
          subject to this student limit.
        </p>
        <p>
          You are responsible for activity performed through your account and for
          deciding whether content is appropriate to store, process, or share with
          connected services.
        </p>
      </LegalSection>

      <LegalSection title="4. Google Classroom connection and authorization">
        <p>
          Connecting Google is optional. The current OAuth flow requests identity
          information (OpenID, email, and profile), read access to courses in which
          you are a student, access to coursework and your own student submissions
          needed for synchronization and submission, and Drive access for files
          created or used by this application. The application does not request
          teacher-side roster or all-student-submission scopes, nor general access
          to every Drive file.
        </p>
        <p>
          You may disconnect Google from Account Settings. Google access depends on
          Google&apos;s availability and your authorization. Disconnecting removes
          the stored Google account credentials and marks cached courses inactive;
          it does not itself delete previously synchronized course or assignment
          records.
        </p>
      </LegalSection>

      <LegalSection title="5. Assignment management and submission workflow">
        <p>
          You can edit and save assignment drafts, review versions, generate PDF or
          DOCX exports, and, for supported Classroom assignments, request submission.
          ClassMate AI requires you to approve the latest saved version before its
          submission workflow can submit the associated PDF to Google Classroom.
          Approval and submission are separate actions; the service does not
          automatically submit a draft.
        </p>
        <p>
          Synchronization may cache course, assignment, deadline, attachment
          metadata, and your own submission status. Attachments are represented by
          metadata and links; the AI workflow does not fetch or read their linked
          contents.
        </p>
      </LegalSection>

      <LegalSection title="6. AI-generated suggestions">
        <p>
          AI output is a suggestion, not verified research, professional advice, or
          a guarantee of accuracy, originality, citation quality, grades, or
          academic success. Review and edit every result, verify claims and sources,
          and make sure your use of AI complies with the rules that apply to your
          course. You remain responsible for content you submit.
        </p>
      </LegalSection>

      <LegalSection title="7. Semester licensing and expiration">
        <p>
          The current seeded semester plan is PKR 500 for six calendar months. The
          plan, price, duration, and payment instructions shown in the application
          at the time of a payment request control if the operator changes the
          available offer. A license begins after an administrator approves the
          payment. An approved renewal extends an active license from its current
          expiry; after expiration or revocation, an approved new term starts at
          approval.
        </p>
        <p>
          After a license expires or is revoked, licensed actions such as new
          synchronization, AI changes, document generation, approval, and Classroom
          submission are blocked. Previously cached Classroom information may
          remain available in read-only views. The license record and payment
          history are not automatically deleted on expiry.
        </p>
      </LegalSection>

      <LegalSection title="8. Payment submission and verification">
        <p>
          Payment is currently handled through operator-configured payment
          instructions and manual administrator review. You may be asked for a
          transaction reference and a JPG, JPEG, or PNG receipt image (up to 5 MiB).
          Submitting a payment request does not activate a license; wait for its
          recorded decision. ClassMate AI does not provide an in-app bank-card
          checkout in the current implementation.
        </p>
      </LegalSection>

      <LegalSection title="9. Cancellation and refunds">
        <p>
          The application supports administrator review, rejection, and recording
          of a refund against an approved payment. It does not process or transfer
          money itself, and there is no student self-service cancellation workflow.
          The code does not define refund eligibility, deadlines, or processing
          times. The operator must confirm and publish a lawful, service-specific
          refund and cancellation policy before accepting paid subscriptions; do
          not infer a refund guarantee or schedule from the application status.
        </p>
      </LegalSection>

      <LegalSection title="10. Acceptable and prohibited use">
        <p>
          Use the service only for lawful purposes and in accordance with
          applicable academic, Google, and service-provider rules. Do not attempt
          unauthorized access, interfere with service operation, misuse another
          person&apos;s account or data, upload malicious material, or use the service
          to infringe another person&apos;s rights. Do not submit AI-assisted work
          where your instructor prohibits it.
        </p>
      </LegalSection>

      <LegalSection title="11. Intellectual property and your content">
        <p>
          You retain whatever rights you have in the assignment materials and
          drafts you provide. You give the service the limited permission needed
          to store, format, generate, and deliver the features you request,
          including sending an approved document to Google Classroom. Do not
          provide content you are not permitted to use. The application and its
          interface remain subject to the rights of their respective owners.
        </p>
      </LegalSection>

      <LegalSection title="12. Service availability and maintenance">
        <p>
          The service may be unavailable, changed, or delayed due to maintenance,
          technical issues, network conditions, or third-party providers. No
          uninterrupted service level or continued availability of Google or AI
          services is promised.
        </p>
      </LegalSection>

      <LegalSection title="13. Suspension and termination">
        <p>
          Access may be restricted where needed to protect accounts, the service,
          other users, or to respond to suspected misuse or legal requirements.
          The application currently has no self-service account deletion feature.
          Account closure and the handling of related records therefore require an
          operator process that must be confirmed before commercial launch.
        </p>
      </LegalSection>

      <LegalSection title="14. Limitations and responsibility">
        <p>
          The service is provided without a promise that AI output, synchronized
          records, exports, or third-party operations will be error-free. To the
          extent permitted by applicable law, the operator disclaims warranties
          that cannot be guaranteed from the implementation. Nothing in these
          terms is intended to exclude rights or liabilities that applicable law
          does not allow to be excluded. This section requires review by qualified
          counsel for the operator&apos;s actual jurisdiction and business model.
        </p>
      </LegalSection>

      <LegalSection title="15. Changes to these terms">
        <p>
          The current Terms version is 2026-11-08. Future changes should be
          published with a new version and date. The current application records
          acceptance at new account registration only; it does not yet have an
          existing-user re-acceptance gate. Pilot users must be presented with
          updated terms and affirmative re-acceptance before paid launch or
          continued use under materially changed terms.
        </p>
      </LegalSection>

      <LegalSection title="16. Contact and disputes">
        <p>
          The repository and application configuration do not identify the legal
          operator, a monitored support or legal-notice email, a physical address,
          or a governing forum. These must be supplied by the owner after legal
          review before the service is offered commercially. No jurisdiction or
          dispute process is invented by this draft.
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
