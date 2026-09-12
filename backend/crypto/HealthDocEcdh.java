import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import javax.crypto.KeyAgreement;
import org.bouncycastle.asn1.x9.X9ECParameters;
import org.bouncycastle.crypto.ec.CustomNamedCurves;
import org.bouncycastle.jce.interfaces.ECPrivateKey;
import org.bouncycastle.jce.interfaces.ECPublicKey;
import org.bouncycastle.jce.provider.BouncyCastleProvider;
import org.bouncycastle.jce.spec.ECParameterSpec;
import org.bouncycastle.jce.spec.ECPrivateKeySpec;
import org.bouncycastle.jce.spec.ECPublicKeySpec;

/** Local, one-shot ECDH bridge. No network, files, CLI secrets or clinical data.
 * All EC operations and point validation belong to Bouncy Castle, not Python.
 * Wire format follows mgrmtech/fidelius-cli revision 4d9b4a5f65d61607dafcea3e28e3d257e425fcd9.
 */
public final class HealthDocEcdh {
    private static final X9ECParameters CURVE = CustomNamedCurves.getByName("curve25519");
    private static final ECParameterSpec SPEC = new ECParameterSpec(
        CURVE.getCurve(), CURVE.getG(), CURVE.getN(), CURVE.getH(), CURVE.getSeed());

    private static byte[] decode(String value) {
        if (value == null || value.length() > 1024) throw new IllegalArgumentException();
        return Base64.getDecoder().decode(value);
    }

    private static String encode(byte[] value) { return Base64.getEncoder().encodeToString(value); }

    public static void main(String[] args) {
        try {
            Security.addProvider(new BouncyCastleProvider());
            // Python bounds the entire input. readNBytes also bounds direct invocation.
            byte[] input = System.in.readNBytes(4097);
            if (input.length > 4096) throw new IllegalArgumentException();
            String[] fields = new String(input, StandardCharsets.US_ASCII).split("\\n");
            if (fields.length == 1 && fields[0].equals("generate")) {
                KeyPairGenerator generator = KeyPairGenerator.getInstance("ECDH", "BC");
                generator.initialize(SPEC, new SecureRandom());
                KeyPair pair = generator.generateKeyPair();
                System.out.println(encode(org.bouncycastle.util.BigIntegers.asUnsignedByteArray(
                    32, ((ECPrivateKey) pair.getPrivate()).getD())));
                System.out.println(encode(((ECPublicKey) pair.getPublic()).getQ().getEncoded(false)));
            } else if (fields.length == 3 && fields[0].equals("derive")) {
                byte[] scalar = decode(fields[1]);
                if (scalar.length != 32) throw new IllegalArgumentException();
                BigInteger d = new BigInteger(1, scalar);
                if (d.signum() <= 0 || d.compareTo(CURVE.getN()) >= 0) throw new IllegalArgumentException();
                KeyFactory factory = KeyFactory.getInstance("ECDH", "BC");
                PrivateKey privateKey = factory.generatePrivate(new ECPrivateKeySpec(d, SPEC));
                byte[] encoded = decode(fields[2]);
                ECPublicKey peer;
                if (encoded.length == 65 && encoded[0] == 4) {
                    peer = (ECPublicKey) factory.generatePublic(new ECPublicKeySpec(
                        SPEC.getCurve().decodePoint(encoded), SPEC));
                } else if (encoded.length > 65 && encoded.length <= 512 && encoded[0] == 0x30) {
                    peer = (ECPublicKey) factory.generatePublic(new X509EncodedKeySpec(encoded));
                } else {
                    throw new IllegalArgumentException();
                }
                ECParameterSpec p = peer.getParameters();
                if (p == null || !p.getCurve().equals(SPEC.getCurve()) || !p.getG().equals(SPEC.getG())
                    || !p.getN().equals(SPEC.getN()) || !p.getH().equals(SPEC.getH())
                    || peer.getQ().isInfinity() || !peer.getQ().isValid()) throw new IllegalArgumentException();
                KeyAgreement agreement = KeyAgreement.getInstance("ECDH", "BC");
                agreement.init(privateKey);
                agreement.doPhase(peer, true);
                System.out.println(encode(agreement.generateSecret()));
            } else {
                throw new IllegalArgumentException();
            }
        } catch (Exception failure) {
            // Never echo input, key bytes or exception messages to application logs.
            System.err.println("ECDH operation refused");
            System.exit(1);
        }
    }
}
