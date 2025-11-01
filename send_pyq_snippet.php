<?php
declare(strict_types=1);

/**
 * Simple SMTP mailer tailored to the QQ Exmail settings provided in the screenshot.
 * It extracts a slice of the pyq-duhougan.md document and sends it as a UTF-8 plain text email.
 */

$config = [
    'host' => 'smtp.exmail.qq.com',
    'port' => 465,
    'encryption' => 'ssl',
    'username' => 'jackie@minteche.com',
    'password' => 'zzgky2KYXtvQsDHV',
    'from_name' => 'Jackie Zheng',
    'recipient' => '274175813@qq.com',
    'timeout' => 20,
];

$markdownPath = __DIR__ . '/pyq-duhougan.md';
$targetHeading = '## Day 1《刻意练习》';

try {
    $snippet = extractSnippet($markdownPath, $targetHeading);
    $subject = 'PyQ日更分享 - ' . $snippet['titleSuffix'];
    $body = $snippet['heading'] . "\n\n" . $snippet['body'];

    sendEmail($config, $subject, $body);
    fwrite(STDOUT, "Email sent successfully.\n");
} catch (Throwable $e) {
    fwrite(STDERR, 'Error: ' . $e->getMessage() . "\n");
    exit(1);
}

/**
 * Pull the markdown content that starts at the specified heading.
 *
 * @return array{heading:string,body:string,titleSuffix:string}
 */
function extractSnippet(string $markdownPath, string $heading): array
{
    if (!is_file($markdownPath)) {
        throw new RuntimeException("Markdown file not found: {$markdownPath}");
    }

    $markdown = file_get_contents($markdownPath);
    if ($markdown === false) {
        throw new RuntimeException("Failed to read markdown file: {$markdownPath}");
    }

    $pattern = '/' . preg_quote($heading, '/') . '\R(.*?)(?:\R---|\z)/us';
    if (!preg_match($pattern, $markdown, $matches)) {
        throw new RuntimeException("Could not locate snippet starting with heading: {$heading}");
    }

    $body = trim($matches[1]);
    $titleSuffix = trim(str_replace('##', '', $heading));

    return [
        'heading' => $heading,
        'body' => $body,
        'titleSuffix' => $titleSuffix,
    ];
}

/**
 * Send a plain text email using direct SMTP commands with AUTH LOGIN.
 *
 * @param array{
 *     host:string,
 *     port:int,
 *     encryption:string,
 *     username:string,
 *     password:string,
 *     from_name:string,
 *     recipient:string,
 *     timeout:int
 * } $config
 */
function sendEmail(array $config, string $subject, string $body): void
{
    if ($config['encryption'] !== 'ssl') {
        throw new InvalidArgumentException('Only SSL encryption is supported by this script.');
    }

    $context = stream_context_create([
        'ssl' => [
            'verify_peer' => true,
            'verify_peer_name' => true,
            'allow_self_signed' => false,
        ],
    ]);

    $remote = sprintf('ssl://%s:%d', $config['host'], $config['port']);
    $socket = @stream_socket_client(
        $remote,
        $errno,
        $errstr,
        $config['timeout'],
        STREAM_CLIENT_CONNECT,
        $context
    );

    if ($socket === false) {
        throw new RuntimeException("Unable to connect to SMTP server: {$errstr} ({$errno})");
    }

    stream_set_timeout($socket, $config['timeout']);

    expectResponse($socket, [220]);

    $hostname = gethostname() ?: 'localhost';
    sendCommand($socket, "EHLO {$hostname}", [250]);

    sendCommand($socket, 'AUTH LOGIN', [334]);
    sendCommand($socket, base64_encode($config['username']), [334]);
    sendCommand($socket, base64_encode($config['password']), [235]);

    sendCommand($socket, "MAIL FROM:<{$config['username']}>", [250]);
    sendCommand($socket, "RCPT TO:<{$config['recipient']}>", [250, 251]);
    sendCommand($socket, 'DATA', [354]);

    $message = buildMessage($config, $subject, $body);
    $message = preg_replace('/^\./m', '..', $message); // dot-stuffing for SMTP
    fwrite($socket, $message);
    fwrite($socket, "\r\n.\r\n");

    expectResponse($socket, [250]);
    sendCommand($socket, 'QUIT', [221]);
    fclose($socket);
}

/**
 * Build MIME headers and normalize the body for SMTP transport.
 */
function buildMessage(array $config, string $subject, string $body): string
{
    $encodedSubject = mb_encode_mimeheader($subject, 'UTF-8');
    $encodedFromName = mb_encode_mimeheader($config['from_name'], 'UTF-8');

    $headers = [
        "From: {$encodedFromName} <{$config['username']}>",
        "To: {$config['recipient']}",
        "Subject: {$encodedSubject}",
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'Content-Transfer-Encoding: 8bit',
    ];

    $headerString = implode("\r\n", $headers);
    $normalizedBody = normalizeLineEndings($body);

    return $headerString . "\r\n\r\n" . $normalizedBody;
}

/**
 * Normalize all line endings to CRLF as required by SMTP.
 */
function normalizeLineEndings(string $text): string
{
    $text = str_replace(["\r\n", "\r"], "\n", $text);
    return str_replace("\n", "\r\n", $text);
}

/**
 * Send a command string and validate the SMTP response code.
 *
 * @param resource $socket
 */
function sendCommand($socket, string $command, array $expectedCodes): string
{
    fwrite($socket, $command . "\r\n");
    return expectResponse($socket, $expectedCodes);
}

/**
 * Read a response from the SMTP socket and ensure it matches expected codes.
 *
 * @param resource $socket
 */
function expectResponse($socket, array $expectedCodes): string
{
    $response = '';
    while (($line = fgets($socket, 515)) !== false) {
        $response .= $line;
        if (strlen($line) >= 4 && $line[3] === ' ') {
            break;
        }
    }

    if ($response === '') {
        throw new RuntimeException('No response from SMTP server.');
    }

    $code = (int)substr($response, 0, 3);
    if (!in_array($code, $expectedCodes, true)) {
        throw new RuntimeException("Unexpected SMTP response: {$response}");
    }

    return $response;
}
