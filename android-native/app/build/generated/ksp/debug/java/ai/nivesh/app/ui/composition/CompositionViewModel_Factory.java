package ai.nivesh.app.ui.composition;

import ai.nivesh.app.data.repo.CompositionRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class CompositionViewModel_Factory implements Factory<CompositionViewModel> {
  private final Provider<CompositionRepository> repoProvider;

  public CompositionViewModel_Factory(Provider<CompositionRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public CompositionViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static CompositionViewModel_Factory create(Provider<CompositionRepository> repoProvider) {
    return new CompositionViewModel_Factory(repoProvider);
  }

  public static CompositionViewModel newInstance(CompositionRepository repo) {
    return new CompositionViewModel(repo);
  }
}
