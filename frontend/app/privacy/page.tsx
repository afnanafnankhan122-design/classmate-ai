import type { Metadata } from "next";
import { LegalPageLayout, LegalSection } from "@/components/legal/legal-page-layout";

export const metadata: Metadata = {
  title: "Privacy Policy | ClassMate AI",
  description: "How ClassMate AI handles account, Classroom, assignment, AI, and payment data.",
};

export default function PrivacyPage() {
  return (
    <LegalPageLayout
      title="Privacy Policy"
      summary="This notice describes data handling visible in the current ClassMate AI codebase. Actual hosting, provider contracts, data locations, operational logs, and backup practices depend on deployment and require owner confirmation."
    >
      <LegalSection title="1. Who this notice covers">
        <p>
          ClassMate AI is an assignment-management application for students. The
          legal operator is not identified in the repository or current application
          configuration. The owner must add the operator&apos;s legal identity and a
          monitored privacy contact before paid launch. This draft is not a
          lawyer-reviewed statement of legal compliance.
        </p>
      </LegalSection>

      <LegalSection title="2. Information the application handles">
        <ul className="list-disc space-y-2 pl-5 marker:text-cyan-300">
          <li>
            <strong className="text-slate-100">Account and profile:</strong> name,
            email, bcrypt password hash for password accounts, optional roll
            number, department, semester, account/provider identifiers, and
            registration and profile timestamps.
          </li>
          <li>
            <strong className="text-slate-100">Consent and authentication:</strong>{" "}
            Terms and Privacy version and acceptance timestamps; signed session
            cookies; an unpredictable browser-device cookie; a SHA-256 hash of the
            device identifier, display-only browser/device label, session expiry,
            last activity, and revocation time. The raw device identifier is not
            stored in the database.
          </li>
          <li>
            <strong className="text-slate-100">Google and coursework:</strong>{" "}
            Google account subject/email, granted scopes, encrypted OAuth tokens
            and expiry, connected/sync timestamps, course metadata, assignment
            titles/instructions/deadlines and attachment metadata/links, and your
            own Classroom submission status.
          </li>
          <li>
            <strong className="text-slate-100">Student work and outputs:</strong>{" "}
            saved assignment drafts, version history, approval records, PDF/DOCX
            exports, submission records, notifications, and AI action/status
            activity. No general student assignment-file upload flow was found;
            the Google attachment data stored is metadata and links.
          </li>
          <li>
            <strong className="text-slate-100">Payments and licensing:</strong>{" "}
            transaction reference, selected payment method/plan, amount and term,
            payment and license status/timestamps, administrator decisions and
            audit metadata, and a receipt image if submitted. The app does not
            include an in-app bank-card checkout or card-number/CVV fields.
          </li>
          <li>
            <strong className="text-slate-100">Password recovery:</strong> hashed
            one-time reset token records, expiry/use state, and email address. A
            configured SMTP relay receives password-reset or password-change
            messages; the reset email contains the one-time reset link.
          </li>
        </ul>
        <p>
          The code includes no analytics or advertising integration that we could
          identify. The host, reverse proxy, database provider, backup system, and
          any infrastructure-level request logging are deployment choices not
          specified in this repository.
        </p>
      </LegalSection>

      <LegalSection title="3. Google Classroom and Drive">
        <p>
          Google connection is optional and is used to synchronize courses and
          coursework, display your own submission status, and carry out a
          submission you explicitly approve. The current OAuth scope set requests
          OpenID, email and profile identity;{" "}
          <code className="break-all text-cyan-200">
            classroom.courses.readonly
          </code>
          ;{" "}
          <code className="break-all text-cyan-200">
            classroom.coursework.me
          </code>{" "}
          for coursework and your own submissions; and{" "}
          <code className="break-all text-cyan-200">drive.file</code> for files
          created or used by the app. It does not request the teacher-side
          <code className="break-all text-cyan-200">
            {" "}classroom.coursework.students
          </code>{" "}
          scope or general access to all Drive files.
        </p>
        <p>
          Google API credentials are encrypted before storage using Fernet
          encryption. On disconnect, the app attempts to revoke the Google token,
          deletes the locally stored Google-account credentials, and marks cached
          courses inactive. Token revocation is best effort; previously cached
          course/assignment data is not deleted by disconnecting. A generated PDF
          is uploaded to your Google Drive and attached to the relevant student
          submission only through the approved submission workflow.
        </p>
        <p>
          Google processes data under its own terms and privacy disclosures. See
          the{" "}
          <a
            href="https://policies.google.com/privacy"
            className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200"
            target="_blank"
            rel="noreferrer"
          >
            Google Privacy Policy
          </a>
          . The application does not control Google&apos;s service availability,
          data handling, or account-level settings.
        </p>
      </LegalSection>

      <LegalSection title="4. AI assistance and Groq">
        <p>
          When you request generation or rewriting and an AI key is configured,
          the server sends a prompt to the Groq API using model identifier{" "}
          <code className="text-cyan-200">openai/gpt-oss-120b</code>. The prompt
          can include the assignment title, course name, instructions, current
          draft, selected passage, custom directions, length/style settings, and
          attachment titles and links. The application does not fetch or send the
          linked attachment contents through this workflow. If a draft or
          instruction contains personal information, that information may be part
          of the prompt.
        </p>
        <p>
          AI output may be inaccurate and should be checked before use or
          submission. The application records AI action/status metadata; the
          provider processes prompt content to return an answer. Groq&apos;s public
          website privacy policy says customer API data is addressed separately
          under its Cloud Services agreements. The operator must confirm which
          Groq agreement and account settings apply to this deployment. We have
          not verified a retention period, training-use setting, or processing
          region for this application and make no promise on those matters. See
          Groq&apos;s{" "}
          <a
            href="https://console.groq.com/docs/legal/services-agreement"
            className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200"
            target="_blank"
            rel="noreferrer"
          >
            Services Agreement
          </a>{" "}
          and{" "}
          <a
            href="https://console.groq.com/docs/legal/customer-data-processing-addendum"
            className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200"
            target="_blank"
            rel="noreferrer"
          >
            Customer Data Processing Addendum
          </a>
          .
        </p>
      </LegalSection>

      <LegalSection title="5. Payments, receipts, and licensing">
        <p>
          Payments are submitted with a transaction reference and, where
          requested, a JPG/JPEG/PNG receipt image of up to 5 MiB. An authorized
          administrator can review the payment details and receipt to approve or
          reject the request and administer the license. The app records the
          payment method, reference, amount, license term, decisions, refund
          metadata, and related audit events. Payment is manually verified; the
          app itself does not collect card numbers or CVV data.
        </p>
        <p>
          Receipt files are stored outside public/static asset directories and
          provided through an administrator-authorized route. The configured
          default receipt cleanup age is 730 days after a payment is finalized
          (approved or rejected); pending receipts are not eligible. Cleanup is
          an operator-run command, not an automatic deletion job. When run, it
          deletes eligible receipt files while retaining payment and audit
          metadata. Production storage and backup handling must be confirmed by
          the operator.
        </p>
      </LegalSection>

      <LegalSection title="6. Why information is used and shared">
        <p>
          Information is used to create and secure accounts, provide the
          assignment workspace, synchronize data at your request or under the
          configured scheduler, generate AI suggestions, create/export documents,
          process administrator-reviewed payments, provide notifications, and
          support and secure the application.
        </p>
        <p>
          Information is sent to Google when you connect and use Classroom/Drive,
          to Groq when you request AI assistance, and to the SMTP provider
          configured by the operator for password-related email. The specific
          SMTP, hosting, database, backup, and file-storage vendors and their
          locations are not identified by the source configuration available for
          this review. The operator must publish the actual production providers
          and confirm their contracts and safeguards before launch. Administrators
          can access payment and receipt information for verification and
          licensing duties.
        </p>
      </LegalSection>

      <LegalSection title="7. Security practices">
        <ul className="list-disc space-y-2 pl-5 marker:text-cyan-300">
          <li>Passwords are stored as salted bcrypt hashes, not plaintext.</li>
          <li>
            Google OAuth credentials are encrypted in the database; the
            encryption key is configured separately.
          </li>
          <li>
            Authentication uses signed, HttpOnly cookies with SameSite=Lax;
            Secure is enabled in production. Device records are checked by the
            server on authenticated requests so revocation takes effect server
            side.
          </li>
          <li>
            The database stores a SHA-256 hash, not the raw device cookie value.
          </li>
          <li>
            Receipt storage is separated from public assets and receipt access is
            restricted to authorized administrator routes.
          </li>
        </ul>
        <p>
          These controls reduce risk but cannot guarantee that an account, device,
          provider, or deployment will never be compromised. Database encryption,
          backups, monitoring, infrastructure access, and incident-response
          procedures depend on deployment and have not been verified here.
        </p>
      </LegalSection>

      <LegalSection title="8. Retention and deletion">
        <p>
          The application does not implement a general account-deletion endpoint
          or automatic deletion schedule for account profiles, cached Classroom
          records, assignment drafts and versions, exports, submission history,
          notifications, consent records, or payment/license audit records. These
          records remain in the configured database until an operator takes an
          appropriate action or the database is otherwise removed. Backup
          retention is not specified in the code.
        </p>
        <ul className="list-disc space-y-2 pl-5 marker:text-cyan-300">
          <li>
            Google tokens are removed from the application when you disconnect
            Google; cached course and assignment records remain stored, with
            courses marked inactive.
          </li>
          <li>
            Password-reset tokens expire after 30 minutes and are marked used or
            invalidated, but no routine database purge for those rows was
            identified.
          </li>
          <li>
            Device sessions expire after 8 hours by default or up to 14 days when
            “Remember me” is used. Revoked and expired device records are not
            automatically purged in the current code.
          </li>
          <li>
            Finalized payment receipt files are eligible for operator-run deletion
            after the configured 730-day default. Pending receipts and payment and
            audit metadata remain. The operator must validate this period against
            applicable recordkeeping requirements and production backups.
          </li>
        </ul>
        <p>
          License expiry disables licensed actions but does not itself delete
          cached Classroom data, drafts, or payment history. An account-deletion
          and retention process, including any records that must be retained, must
          be defined by the operator and reviewed before commercial launch.
        </p>
      </LegalSection>

      <LegalSection title="9. Your choices and privacy requests">
        <p>
          You can update some profile fields in Account Settings, change your
          password, disconnect Google, and revoke registered device sessions.
          Email, data export, and account deletion are not self-service features
          identified in the current application. To request access to, correction
          of, or deletion of information, use the privacy contact that the
          operator must publish before launch. No such contact is currently
          configured in this application, so the owner must supply one before
          accepting paid users. Requests may be subject to records the operator
          must retain under applicable law.
        </p>
      </LegalSection>

      <LegalSection title="10. International processing and service providers">
        <p>
          The repository allows either SQLite or PostgreSQL and a configurable
          receipt directory; it does not identify the production host, database
          vendor, SMTP company, backup provider, or server/data region. Google
          and Groq are integrated external services, but the code does not
          establish the locations where their services process or store this
          deployment&apos;s data. The operator must document the actual hosting and
          vendor locations; this notice does not claim that data stays in Pakistan
          or any other country.
        </p>
      </LegalSection>

      <LegalSection title="11. Children and age requirements">
        <p>
          The application has no age-verification field or configured minimum-age
          rule. The operator must decide and publish an age policy and any
          required parent/guardian process after legal review, especially because
          the service is intended for students.
        </p>
      </LegalSection>

      <LegalSection title="12. Changes, legal context, and contact">
        <p>
          This Privacy Policy is version 2026-11-08. A material change should be
          published with a new version and date and presented to existing pilot
          users for affirmative acknowledgment before paid launch. Existing
          accounts are not silently marked as having accepted this version.
        </p>
        <p>
          Pakistani legal requirements may depend on the operator, users,
          providers, and actual processing. The official{" "}
          <a
            href="https://pakistancode.gov.pk/english/sHyuRiF.php"
            className="text-cyan-300 underline underline-offset-4 hover:text-cyan-200"
            target="_blank"
            rel="noreferrer"
          >
            Pakistan Code federal laws collection
          </a>{" "}
          was consulted as an authoritative starting point, but this application
          review does not determine which current federal or provincial privacy,
          electronic-transactions, consumer, tax, or education rules apply. The
          operator must obtain qualified Pakistani legal advice and confirm the
          applicable instruments, user-request process, and any cross-border
          requirements before launch.
        </p>
        <p>
          The operator&apos;s legal name, privacy email or other monitored contact,
          address, and complaint route are not configured in the application and
          must be provided by the owner. No contact details, server location, or
          governing jurisdiction are invented here.
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
