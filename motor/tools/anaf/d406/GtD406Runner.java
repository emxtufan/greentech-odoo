// Local launcher only. All fiscal validation/PDF code remains in ANAF's jars.
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import dec.Info;
import d406validator.Validator;

public final class GtD406Runner {
    public static void main(String[] args) throws Exception {
        if (args.length != 8 || !"D406".equals(args[1]))
            throw new IllegalArgumentException("mode D406 xml errors pdf year month type");
        String mode = args[0], xml = args[2], errors = args[3], pdf = args[4];
        int year = Integer.parseInt(args[5]), month = Integer.parseInt(args[6]);
        if ((!mode.equals("validate") && !mode.equals("pdf")) ||
                year < 2000 || year > 2100 || month < 1 || month > 12 ||
                !args[7].matches("L|T|NL|NT"))
            throw new IllegalArgumentException("Invalid mode or reporting period");
        dec.LogTrace.init(errors + ".log", errors + ".trace", 1, 0, true);
        Validator validator = new Validator();
        int status = validator.parseDocument(xml, errors, year, month, args[7]);
        if (status != 0) {
            System.err.println("ANAF_VALIDATION_STATUS=" + status);
            System.exit(2);
        }
        Info info = validator.getInfo();
        if (Integer.parseInt(info._an) != year || Integer.parseInt(info._luna) != month)
            throw new IllegalStateException("ANAF period differs from requested period");
        if (mode.equals("pdf")) {
            String result = new d406.Pdf_v0().createPdf(info, pdf, xml, null);
            if (result == null || !result.isEmpty() || !Files.exists(Paths.get(pdf)))
                throw new IllegalStateException("ANAF PDF: " + result);
        }
        Files.write(Paths.get(errors), "ok".getBytes(StandardCharsets.UTF_8));
        System.out.println("GT_D406_ANAF_VALID year=" + year + " month=" + month);
    }
}
