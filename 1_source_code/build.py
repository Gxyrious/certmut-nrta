from pathlib import Path
from shutil import copy2, copytree
from subprocess import run
from tempfile import TemporaryDirectory

SOURCE = Path(__file__).resolve().parent
UPSTREAM = "https://github.com/zeno-98/NRTA_Learning.git"
REVISION = "18ddd90798f05285884946fece11fa0ed6100770"
PROJECT = "1_Source_Code/NRTA_Learning"


def build():
    with TemporaryDirectory() as directory:
        run(["git", "init", "-q"], cwd=directory, check=True)
        run(["git", "fetch", "-q", "--depth=1", UPSTREAM, REVISION], cwd=directory, check=True)
        run(["git", "checkout", "-q", "FETCH_HEAD", "--", PROJECT], cwd=directory, check=True)
        project = Path(directory) / PROJECT
        java = project / "src/main/java"
        copytree(SOURCE / "java", java, dirs_exist_ok=True)

        entry = java / "CompositionLearningMain.java"
        entry.write_text(entry.read_text().replace(
            "new Teacher(targetNta, this.slv)", "new research.TestTeacher(targetNta, this.slv)"
        ).replace(
            "ResetLogicalTimedWord.setKMap(targetNta.getK_map());",
            "ResetLogicalTimedWord.setKMap(targetNta.getAllClocks().stream().collect("
            "java.util.stream.Collectors.toMap(c -> c, c -> Value.INFINITE)));"
        ).replace(
            "if (LearningSetting.isLearningQuiet()) {",
            "if (LearningSetting.isLearningQuiet() && System.console() != null) {"
        ))
        table = java / "learning/learners/composition_table/multiple_RTA_learners/table/Table.java"
        source = table.read_text()
        start = source.index('            solverKind = "Optimize";')
        stop = source.index('            if (solveStatus != Status.SATISFIABLE)', start)
        source = source[:start] + """            solverKind = "IncrementalCanonicalSAT";
            List<ElementNode> nodes = new ArrayList<>();
            for (ElementNode node : this.elementTree) {
                if (node.isAccept() == TriBool.unknown) nodes.add(node);
            }
            nodes.sort(Comparator.comparing(ElementNode::wordToString));
            List<BitVecExpr> objectives = new ArrayList<>();
            for (ElementNode node : nodes) objectives.add(node.getBvAccept());
            for (Prefix prefix : this.sortPrefixes(this.s_area)) objectives.add(prefix.rowSmtExpr());
            for (Prefix prefix : this.sortPrefixes(this.r_area)) objectives.add(prefix.rowSmtExpr());
            research.CanonicalSolver.Result result = research.CanonicalSolver.solve(
                    this.slv, objectives, closedConstraint, consistentConstraint, sinkConstraint);
            solverInput = result.input();
            solveStatus = result.status();
""" + source[stop:]
        table.write_text(source.replace("model = opt.getModel();", "model = result.model();"))

        run(["mvn", "-B", "-q", "-DskipTests", "package"], cwd=project, check=True)
        output = SOURCE / "lib"
        output.mkdir(exist_ok=True)
        copy2(project / "target/Multi_TA_Learning-1.0-SNAPSHOT.jar", output / "learner.jar")


if __name__ == "__main__":
    build()
