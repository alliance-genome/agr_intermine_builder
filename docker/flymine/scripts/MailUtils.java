package org.intermine.util;

import java.text.MessageFormat;
import java.util.Date;
import java.util.Properties;

import javax.mail.Authenticator;
import javax.mail.Message;
import javax.mail.MessagingException;
import javax.mail.PasswordAuthentication;
import javax.mail.Session;
import javax.mail.Transport;
import javax.mail.internet.InternetAddress;
import javax.mail.internet.MimeMessage;

import org.apache.commons.lang.StringUtils;

/**
 * PATCHED 2026-05-27: upstream InterMine 1.x sets the message From header to
 * the SMTP username when authentication is enabled. That assumes the SMTP user
 * is itself an email address (Gmail-style relay). For AWS SES SMTP, the user
 * is an IAM access key ID (AKIA...) and SES rejects with "554 User name is
 * missing". This patch always uses mail.from for the From header regardless
 * of mail.smtp.user.
 */
public abstract class MailUtils {

    private MailUtils() { }

    public static void email(String to, String subject, String text, String from,
                              Properties webProperties) throws MessagingException {
        final String smtpUser = webProperties.getProperty("mail.smtp.user");
        String smtpPort = webProperties.getProperty("mail.smtp.port");
        String smtpAuth = webProperties.getProperty("mail.smtp.auth");
        String smtpStarttls = webProperties.getProperty("mail.smtp.starttls.enable");

        Properties properties = System.getProperties();
        properties.put("mail.smtp.host", webProperties.get("mail.host"));
        if (!StringUtils.isEmpty(smtpUser)) {
            properties.put("mail.smtp.user", smtpUser);
            properties.put("mail.smtp.localhost", "localhost");
        }
        if (smtpPort != null) properties.put("mail.smtp.port", smtpPort);
        if (smtpStarttls != null) properties.put("mail.smtp.starttls.enable", smtpStarttls);
        if (smtpAuth != null) properties.put("mail.smtp.auth", smtpAuth);

        Session session;
        if ("true".equals(smtpAuth) || "t".equals(smtpAuth)) {
            final Properties wp = webProperties;
            Authenticator auth = new Authenticator() {
                protected PasswordAuthentication getPasswordAuthentication() {
                    return new PasswordAuthentication(smtpUser,
                            wp.getProperty("mail.server.password"));
                }
            };
            session = Session.getInstance(properties, auth);
        } else {
            session = Session.getInstance(properties);
        }

        MimeMessage msg = new MimeMessage(session);
        msg.setFrom(new InternetAddress(from));
        msg.addRecipient(Message.RecipientType.TO, InternetAddress.parse(to, true)[0]);
        msg.setSubject(subject);
        msg.setSentDate(new Date());
        msg.setContent(text, "text/plain");
        Transport.send(msg);
    }

    public static void email(String to, String subject, String text, Properties webProperties)
            throws MessagingException {
        String from = (String) webProperties.get("mail.from");
        email(to, subject, text, from, webProperties);
    }

    public static void welcome(String to, Properties webProperties) throws MessagingException {
        String subject = (String) webProperties.get("mail.subject");
        String text = (String) webProperties.get("mail.text");
        email(to, subject, text, webProperties);
    }

    public static void emailPasswordToken(String to, String token, Properties webProperties)
            throws Exception {
        String projectTitle = (String) webProperties.get("project.title");
        String subjectTemplate = (String) webProperties.get("mail.passwordSubject");
        String subject = MessageFormat.format(subjectTemplate, new Object[] { projectTitle });
        String textTemplate = (String) webProperties.get("mail.passwordText");
        String body = MessageFormat.format(textTemplate, new Object[] { token });
        email(to, subject, body, webProperties);
    }

    public static void subscribe(String fromEmail, Properties webProperties) throws MessagingException {
        String mailingList = (String) webProperties.get("mail.mailing-list");
        if (mailingList != null) {
            email(mailingList, "subscribe", "subscribe", fromEmail, webProperties);
        }
    }
}
